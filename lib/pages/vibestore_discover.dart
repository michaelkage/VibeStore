import 'dart:convert';

import 'package:file_picker/file_picker.dart';

import 'package:material_ui/material_ui.dart';
import 'package:obtainium/services/vibestore_api.dart';
import 'package:url_launcher/url_launcher.dart';

class VibeStoreDiscoverPage extends StatefulWidget {
  const VibeStoreDiscoverPage({super.key});

  @override
  State<VibeStoreDiscoverPage> createState() => _VibeStoreDiscoverPageState();
}

class _VibeStoreDiscoverPageState extends State<VibeStoreDiscoverPage> {
  static final Uri _websiteUri = Uri.parse(
    'https://michaelkage.github.io/VibeStore/',
  );

  final _baseUrlController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _queryController = TextEditingController();
  final _minimumStarsController = TextEditingController();
  final _fileQueryController = TextEditingController();
  String _searchLicense = 'any';
  final _repositoryController = TextEditingController();
  final _remixPromptController = TextEditingController();

  VibeStoreApi? _api;
  List<Map<String, dynamic>> _results = [];
  List<Map<String, dynamic>> _catalog = [];
  List<Map<String, dynamic>> _library = [];
  final Set<String> _favoriteIds = {};
  List<Map<String, dynamic>> _repositoryFiles = [];
  int _repositoryFileTotal = 0;
  final Set<String> _selectedSourcePaths = {};
  int _catalogTotal = 0;
  String _catalogSort = 'popular';
  List<Map<String, dynamic>> _submissions = [];
  List<Map<String, dynamic>> _remixSessions = [];
  List<Map<String, dynamic>> _remixProposals = [];
  Map<String, dynamic>? _activeRemix;
  String? _inspection;
  String? _notice;
  String? _error;
  bool _initializing = true;
  bool _busy = false;

  bool _supportsPatchRemix(Map<String, dynamic> app) {
    final repository = Uri.tryParse(app['repository_url']?.toString() ?? '');
    return repository?.scheme == 'https' &&
        repository?.host.toLowerCase() == 'github.com';
  }

  Future<void> _openWebsite() async {
    try {
      final opened = await launchUrl(
        _websiteUri,
        mode: LaunchMode.externalApplication,
      );
      if (!opened && mounted) {
        setState(() => _error = 'Unable to open the VibeStore website.');
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = 'Unable to open the VibeStore website: $error');
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    try {
      final api = await VibeStoreApi.load();
      if (!mounted) {
        api.dispose();
        return;
      }
      setState(() {
        _api = api;
        _baseUrlController.text = api.baseUrl;
        _initializing = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
        _initializing = false;
      });
    }
  }

  @override
  void dispose() {
    _api?.dispose();
    _baseUrlController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _queryController.dispose();
    _minimumStarsController.dispose();
    _fileQueryController.dispose();
    _repositoryController.dispose();
    _remixPromptController.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _configure() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    setState(() {
      _results = [];
      _inspection = null;
      _submissions = [];
      _notice = 'API address saved. Sign in to index repositories.';
    });
  });

  Future<void> _authenticate({required bool createAccount}) => _run(() async {
    final api = _api!;
    await api.configureBaseUrl(_baseUrlController.text);
    final user = createAccount
        ? await api.register(_emailController.text, _passwordController.text)
        : await api.login(_emailController.text, _passwordController.text);
    if (!mounted) return;
    setState(() {
      _passwordController.clear();
      _notice = 'Signed in as ${user['email']}.';
    });
  });

  Future<void> _loadLibrary() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final items = await _api!.myLibrary();
    if (!mounted) return;
    setState(() {
      _library = items;
      _favoriteIds
        ..clear()
        ..addAll(
          items
              .where((item) => item['favorited_at'] != null)
              .map((item) => item['id'].toString()),
        );
      _notice = 'Loaded ${items.length} apps in your library.';
    });
  });

  Future<void> _toggleFavorite(Map<String, dynamic> app) => _run(() async {
    final appId = app['id'].toString();
    await _api!.configureBaseUrl(_baseUrlController.text);
    if (_favoriteIds.contains(appId)) {
      await _api!.unfavoriteApp(appId);
    } else {
      await _api!.favoriteApp(appId);
    }
    final items = await _api!.myLibrary();
    if (!mounted) return;
    setState(() {
      _library = items;
      _favoriteIds
        ..clear()
        ..addAll(
          items
              .where((item) => item['favorited_at'] != null)
              .map((item) => item['id'].toString()),
        );
    });
  });

  Future<void> _loadCatalog() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final response = await _api!.catalog(sort: _catalogSort);
    if (!mounted) return;
    final items = response['items'] as List;
    setState(() {
      _catalog = items
          .map((value) => Map<String, dynamic>.from(value as Map))
          .toList(growable: false);
      _catalogTotal = response['total'] as int? ?? _catalog.length;
      _notice = 'Showing ${_catalog.length} of $_catalogTotal catalog apps.';
    });
  });

  Future<void> _search() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final minimumStarsText = _minimumStarsController.text.trim();
    final minimumStars = minimumStarsText.isEmpty
        ? null
        : int.tryParse(minimumStarsText);
    if (minimumStarsText.isNotEmpty && minimumStars == null) {
      throw const VibeStoreApiException(
        'Minimum stars must be a whole number.',
      );
    }
    final results = await _api!.search(
      _queryController.text,
      license: _searchLicense == 'any' ? null : _searchLicense,
      minStars: minimumStars,
    );
    if (!mounted) return;
    setState(() {
      _results = results;
      _notice = '${results.length} result(s) found.';
    });
  });

  Future<void> _loadMyRepositories() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final repositories = await _api!.myRepositories();
    if (!mounted) return;
    setState(() {
      _submissions = repositories;
      _notice =
          '${repositories.length} submitted repository/repositories loaded.';
    });
  });

  Future<void> _indexRepository() => _run(() async {
    final api = _api!;
    await api.configureBaseUrl(_baseUrlController.text);
    final queued = await api.enqueueRepositoryIndex(_repositoryController.text);
    final jobId = queued['id'] as String;
    if (mounted) {
      setState(
        () => _notice = 'Repository queued for background indexing ($jobId).',
      );
    }
    for (var attempt = 0; attempt < 200; attempt++) {
      await Future.delayed(const Duration(seconds: 2));
      if (!mounted) return;
      final job = await api.repositoryIndexJob(jobId);
      final jobStatus = job['status']?.toString() ?? 'unknown';
      if (jobStatus == 'completed') {
        final repositories = await api.myRepositories();
        String? inspectionNotice;
        final appId = job['app_id']?.toString();
        if (appId != null && appId.isNotEmpty) {
          try {
            final cached = await api.cachedInspection(appId);
            _inspection = const JsonEncoder.withIndent(
              '  ',
            ).convert(cached['report'] ?? cached);
          } catch (error) {
            inspectionNotice = 'Inspection report is not available yet: $error';
          }
        }
        if (!mounted) return;
        setState(() {
          _submissions = repositories;
          _notice =
              inspectionNotice ??
              'Repository indexed and cached inspection report loaded.';
        });
        return;
      }
      if (jobStatus == 'failed') {
        throw VibeStoreApiException(
          job['error']?.toString() ?? 'Repository indexing failed.',
        );
      }
      setState(() {
        _notice =
            'Indexing repository… $jobStatus (attempt ${job['attempt_count'] ?? 0}).';
      });
    }
    throw VibeStoreApiException(
      'Indexing is still running. Job ID: $jobId. Refresh the collection later.',
    );
  });

  Future<void> _loadRemixSessions() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final sessions = await _api!.remixSessions();
    if (!mounted) return;
    setState(() {
      _remixSessions = sessions;
      _notice = '${sessions.length} remix session(s) loaded.';
    });
  });

  Future<void> _createRemix(String appId, String appName) => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final safeName = appName.length > 110
        ? '${appName.substring(0, 107)}…'
        : appName;
    final created = await _api!.createRemixSession(
      appId,
      title: 'Remix · $safeName',
    );
    final session = await _api!.remixSession(created['id'].toString());
    final sessions = await _api!.remixSessions();
    if (!mounted) return;
    setState(() {
      _activeRemix = session;
      _remixSessions = sessions;
      _remixProposals = [];
      _repositoryFiles = [];
      _repositoryFileTotal = 0;
      _selectedSourcePaths.clear();
      _remixPromptController.clear();
      _notice =
          'Remix session created for $appName at commit ${session['source_commit_sha']}.';
    });
  });

  Future<void> _openRemix(String remixId) => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final session = await _api!.remixSession(remixId);
    final proposals = await _api!.remixPatchProposals(remixId);
    if (!mounted) return;
    setState(() {
      _activeRemix = session;
      _remixProposals = proposals;
      _repositoryFiles = [];
      _repositoryFileTotal = 0;
      _selectedSourcePaths.clear();
      _notice = 'Opened remix session: ${session['title']}.';
    });
  });

  Future<void> _loadRemixFiles() => _run(() async {
    final active = _activeRemix;
    if (active == null) return;
    final appId = active['app_id']?.toString();
    if (appId == null || appId.isEmpty) {
      throw const VibeStoreApiException(
        'The active remix does not identify its source application.',
      );
    }
    await _api!.configureBaseUrl(_baseUrlController.text);
    final response = await _api!.repositoryFiles(
      appId,
      query: _fileQueryController.text,
      limit: 50,
    );
    if (!mounted) return;
    final items = response['items'] as List;
    setState(() {
      _repositoryFiles = items
          .map((value) => Map<String, dynamic>.from(value as Map))
          .toList(growable: false);
      _repositoryFileTotal =
          response['total'] as int? ?? _repositoryFiles.length;
      _notice =
          'Loaded ${_repositoryFiles.length} of $_repositoryFileTotal indexed source files.';
    });
  });

  Future<void> _sendRemixMessage() => _run(() async {
    final active = _activeRemix;
    final prompt = _remixPromptController.text.trim();
    if (active == null || prompt.length < 3) {
      throw const VibeStoreApiException(
        'Enter a change request with at least 3 characters.',
      );
    }
    await _api!.configureBaseUrl(_baseUrlController.text);
    await _api!.sendRemixMessage(
      active['id'].toString(),
      prompt,
      contextPaths: _selectedSourcePaths.toList(),
    );
    final session = await _api!.remixSession(active['id'].toString());
    if (!mounted) return;
    setState(() {
      _activeRemix = session;
      _remixPromptController.clear();
      _notice =
          'Change plan generated. Review the evidence and validation steps below.';
    });
  });

  Future<void> _generatePatchProposal() => _run(() async {
    final active = _activeRemix;
    final prompt = _remixPromptController.text.trim();
    if (active == null || prompt.length < 3) {
      throw const VibeStoreApiException(
        'Enter a change request with at least 3 characters.',
      );
    }
    await _api!.configureBaseUrl(_baseUrlController.text);
    await _api!.generateRemixPatchProposal(
      active['id'].toString(),
      prompt,
      contextPaths: _selectedSourcePaths.take(12).toList(),
    );
    final proposals = await _api!.remixPatchProposals(active['id'].toString());
    if (!mounted) return;
    setState(() {
      _remixProposals = proposals;
      _notice =
          'Review-only patch draft generated. It has not changed any source files.';
    });
  });

  Future<void> _validatePatchProposal(String proposalId) => _run(() async {
    final active = _activeRemix;
    if (active == null) return;
    await _api!.configureBaseUrl(_baseUrlController.text);
    await _api!.validateRemixPatchProposal(active['id'].toString(), proposalId);
    final proposals = await _api!.remixPatchProposals(active['id'].toString());
    if (!mounted) return;
    final validated = proposals.firstWhere(
      (proposal) => proposal['id'] == proposalId,
      orElse: () => const <String, dynamic>{},
    );
    setState(() {
      _remixProposals = proposals;
      _notice = validated['validation_status'] == 'applicable'
          ? 'Source verification passed. The diff matches the complete pinned files; nothing was written.'
          : 'Source verification could not validate this diff. Review the validation report.';
    });
  });

  Future<void> _reviewPatchProposal(String proposalId, String decision) =>
      _run(() async {
        final active = _activeRemix;
        if (active == null) return;
        await _api!.configureBaseUrl(_baseUrlController.text);
        await _api!.reviewRemixPatchProposal(
          active['id'].toString(),
          proposalId,
          decision,
        );
        final proposals = await _api!.remixPatchProposals(
          active['id'].toString(),
        );
        if (!mounted) return;
        setState(() {
          _remixProposals = proposals;
          _notice = decision == 'approved'
              ? 'Proposal marked approved for review. No files were modified.'
              : 'Proposal rejected. No files were modified.';
        });
      });

  Future<void> _processApprovedProposal(String proposalId) => _run(() async {
    final active = _activeRemix;
    if (active == null) return;
    final remixId = active['id'].toString();
    await _api!.configureBaseUrl(_baseUrlController.text);
    await _api!.processApprovedPatch(remixId, proposalId);
    for (var attempt = 0; attempt < 60; attempt++) {
      await Future.delayed(const Duration(seconds: 2));
      if (!mounted) return;
      final response = await _api!.patchArtifact(remixId, proposalId);
      if (response.headers['content-type']?.contains('application/zip') ??
          false) {
        final savedPath = await FilePicker.saveFile(
          fileName: 'vibestore-patch-$proposalId.zip',
          bytes: response.bodyBytes,
        );
        if (!mounted) return;
        setState(() {
          _notice = savedPath == null
              ? 'Source ZIP is ready; saving was cancelled.'
              : 'Review-only source ZIP saved to $savedPath';
        });
        return;
      }
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      final status = decoded is Map
          ? decoded['status']?.toString() ?? 'processing'
          : 'processing';
      if (status == 'failed') {
        throw VibeStoreApiException(
          decoded is Map
              ? decoded['error']?.toString() ?? 'Patch processing failed.'
              : 'Patch processing failed.',
        );
      }
      if (mounted) {
        setState(() => _notice = 'Preparing changed-source ZIP… $status');
      }
    }
    throw const VibeStoreApiException(
      'Source ZIP preparation is still running. Reopen the proposal and try again shortly.',
    );
  });

  Future<void> _removeSubmission(String appId, String name) => _run(() async {
    await _api!.removeMyRepository(appId);
    final repositories = await _api!.myRepositories();
    if (!mounted) return;
    setState(() {
      _submissions = repositories;
      _notice =
          'Removed $name from your collection. The shared catalog entry is unchanged.';
    });
  });

  Future<void> _inspectRepository() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final result = await _api!.inspectRepository(_repositoryController.text);
    if (!mounted) return;
    setState(() {
      _inspection = const JsonEncoder.withIndent('  ').convert(result);
      _notice = 'Static repository inspection completed.';
    });
  });

  Future<void> _loadCachedInspection(String appId, String appName) =>
      _run(() async {
        await _api!.configureBaseUrl(_baseUrlController.text);
        final cached = await _api!.cachedInspection(appId);
        if (!mounted) return;
        setState(() {
          _inspection = const JsonEncoder.withIndent(
            '  ',
          ).convert(cached['report'] ?? cached);
          _notice = 'Loaded cached X-Ray report for $appName.';
        });
      });

  Future<void> _logout() async {
    await _api?.logout();
    if (mounted) setState(() => _notice = 'Signed out.');
  }

  Widget _section(String title, IconData icon, List<Widget> children) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            ...children,
          ],
        ),
      ),
    );
  }

  Widget _textField(
    TextEditingController controller,
    String label, {
    String? hint,
    bool obscure = false,
    TextInputType? keyboardType,
    int maxLines = 1,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      keyboardType: keyboardType,
      maxLines: obscure ? 1 : maxLines,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        border: const OutlineInputBorder(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_initializing) {
      return Scaffold(
        appBar: AppBar(
          title: const Text('VibeStore discovery'),
          actions: [
            IconButton(
              onPressed: _openWebsite,
              tooltip: 'VibeStore website',
              icon: const Icon(Icons.public_rounded),
            ),
          ],
        ),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    final api = _api;
    return Scaffold(
      appBar: AppBar(
        title: const Text('VibeStore discovery'),
        actions: [
          IconButton(
            onPressed: _openWebsite,
            tooltip: 'VibeStore website',
            icon: const Icon(Icons.public_rounded),
          ),
          if (api?.isAuthenticated == true)
            IconButton(
              onPressed: _busy ? null : _logout,
              tooltip: 'Sign out',
              icon: const Icon(Icons.logout_rounded),
            ),
        ],
      ),
      body: api == null
          ? Center(child: Text(_error ?? 'Unable to initialize VibeStore API.'))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _section('API connection', Icons.cloud_outlined, [
                  _textField(
                    _baseUrlController,
                    'API base URL',
                    hint: 'https://api.example.com',
                    keyboardType: TextInputType.url,
                  ),
                  const SizedBox(height: 12),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.tonalIcon(
                      onPressed: _busy ? null : _configure,
                      icon: const Icon(Icons.save_outlined),
                      label: const Text('Save address'),
                    ),
                  ),
                  const Text(
                    'Use your deployed HTTPS API. For Android emulator development, http://10.0.2.2:8000 is allowed in debug builds.',
                  ),
                ]),
                _section('Account', Icons.person_outline_rounded, [
                  _textField(
                    _emailController,
                    'Email',
                    keyboardType: TextInputType.emailAddress,
                  ),
                  const SizedBox(height: 12),
                  _textField(_passwordController, 'Password', obscure: true),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilledButton(
                        onPressed: _busy
                            ? null
                            : () => _authenticate(createAccount: false),
                        child: const Text('Sign in'),
                      ),
                      OutlinedButton(
                        onPressed: _busy
                            ? null
                            : () => _authenticate(createAccount: true),
                        child: const Text('Create account'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    api.isAuthenticated
                        ? 'Authenticated. Repository indexing is enabled.'
                        : 'Sign in to submit repositories. Your access token is stored using platform secure storage.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ]),

                _section('My repositories', Icons.folder_open_outlined, [
                  Align(
                    alignment: Alignment.centerRight,
                    child: OutlinedButton.icon(
                      onPressed: _busy || !api.isAuthenticated
                          ? null
                          : _loadMyRepositories,
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Refresh collection'),
                    ),
                  ),
                  if (!api.isAuthenticated)
                    const Text(
                      'Sign in to view and manage your submitted repositories.',
                    )
                  else if (_submissions.isEmpty)
                    const Text(
                      'No submitted repositories loaded. Refresh to check your collection.',
                    )
                  else
                    for (final repository in _submissions)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(
                          repository['name']?.toString() ??
                              'Unnamed repository',
                        ),
                        subtitle: Text(
                          [
                            repository['repository_url']?.toString() ?? '',
                            '${repository['stars'] ?? 0} stars · ${repository['default_branch'] ?? 'unknown branch'}',
                          ].where((value) => value.isNotEmpty).join('\\n'),
                        ),
                        trailing: IconButton(
                          tooltip: 'Remove from my collection',
                          onPressed: _busy
                              ? null
                              : () => _removeSubmission(
                                  repository['id'].toString(),
                                  repository['name']?.toString() ??
                                      'repository',
                                ),
                          icon: const Icon(Icons.remove_circle_outline_rounded),
                        ),
                        isThreeLine: true,
                      ),
                ]),
                _section('App catalog', Icons.apps_rounded, [
                  Row(
                    children: [
                      const Text('Sort by'),
                      const SizedBox(width: 12),
                      DropdownButton<String>(
                        value: _catalogSort,
                        items: const [
                          DropdownMenuItem(
                            value: 'popular',
                            child: Text('Most popular'),
                          ),
                          DropdownMenuItem(
                            value: 'recent',
                            child: Text('Recently indexed'),
                          ),
                          DropdownMenuItem(
                            value: 'name',
                            child: Text('Name A–Z'),
                          ),
                        ],
                        onChanged: _busy
                            ? null
                            : (value) async {
                                if (value == null) return;
                                setState(() => _catalogSort = value);
                                await _loadCatalog();
                              },
                      ),
                      const Spacer(),
                      FilledButton.tonalIcon(
                        onPressed: _busy ? null : _loadCatalog,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Browse'),
                      ),
                    ],
                  ),
                  if (_catalog.isEmpty)
                    const Text(
                      'Browse the indexed open-source Android app catalog.',
                    )
                  else ...[
                    Text('$_catalogTotal apps in the catalog'),
                    const Divider(height: 16),
                    for (final app in _catalog)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        onTap: _busy
                            ? null
                            : () => _loadCachedInspection(
                                app['id'].toString(),
                                app['name']?.toString() ?? 'app',
                              ),
                        title: Text(app['name']?.toString() ?? 'Unnamed app'),
                        subtitle: Text(
                          [
                            app['description']?.toString() ?? '',
                            if (app['license'] != null)
                              'License: ${app['license']}',
                            app['repository_url']?.toString() ?? '',
                          ].where((value) => value.isNotEmpty).join(' · '),
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text('★ ${app['stars'] ?? 0}'),
                            if (api.isAuthenticated)
                              IconButton(
                                tooltip:
                                    _favoriteIds.contains(app['id'].toString())
                                    ? 'Remove from library'
                                    : 'Add to library',
                                onPressed: _busy
                                    ? null
                                    : () => _toggleFavorite(app),
                                icon: Icon(
                                  _favoriteIds.contains(app['id'].toString())
                                      ? Icons.bookmark
                                      : Icons.bookmark_border,
                                ),
                              ),
                            if (api.isAuthenticated && _supportsPatchRemix(app))
                              IconButton(
                                tooltip: 'Start a remix',
                                onPressed: _busy
                                    ? null
                                    : () => _createRemix(
                                        app['id'].toString(),
                                        app['name']?.toString() ?? 'app',
                                      ),
                                icon: const Icon(Icons.auto_awesome_rounded),
                              ),
                          ],
                        ),
                        isThreeLine: true,
                      ),
                  ],
                ]),
                _section('Discover apps', Icons.travel_explore_rounded, [
                  _textField(
                    _queryController,
                    'Describe what you are looking for',
                    hint: 'A private notes app with offline sync',
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          initialValue: _searchLicense,
                          decoration: const InputDecoration(
                            labelText: 'License',
                            border: OutlineInputBorder(),
                          ),
                          items: const [
                            DropdownMenuItem(
                              value: 'any',
                              child: Text('Any license'),
                            ),
                            DropdownMenuItem(value: 'MIT', child: Text('MIT')),
                            DropdownMenuItem(
                              value: 'Apache-2.0',
                              child: Text('Apache-2.0'),
                            ),
                            DropdownMenuItem(
                              value: 'GPL-3.0',
                              child: Text('GPL-3.0'),
                            ),
                          ],
                          onChanged: _busy
                              ? null
                              : (value) {
                                  if (value != null) {
                                    setState(() => _searchLicense = value);
                                  }
                                },
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _textField(
                          _minimumStarsController,
                          'Minimum stars',
                          keyboardType: TextInputType.number,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
                      onPressed: _busy ? null : _search,
                      icon: const Icon(Icons.search_rounded),
                      label: const Text('Search catalog'),
                    ),
                  ),
                  if (_results.isNotEmpty) ...[
                    const Divider(height: 24),
                    for (final result in _results)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        onTap: _busy
                            ? null
                            : () => _loadCachedInspection(
                                result['id'].toString(),
                                result['name']?.toString() ?? 'app',
                              ),
                        title: Text(
                          result['name']?.toString() ?? 'Unnamed app',
                        ),
                        subtitle: Text(
                          [
                            result['description']?.toString() ?? '',
                            result['repository_url']?.toString() ?? '',
                          ].where((value) => value.isNotEmpty).join('\n'),
                        ),
                        trailing: Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            if (api.isAuthenticated &&
                                _supportsPatchRemix(result))
                              IconButton(
                                tooltip: 'Start a remix',
                                onPressed: _busy
                                    ? null
                                    : () => _createRemix(
                                        result['id'].toString(),
                                        result['name']?.toString() ?? 'app',
                                      ),
                                icon: const Icon(Icons.auto_awesome_rounded),
                              ),
                            Text(
                              (result['score'] as num?)?.toStringAsFixed(2) ??
                                  '',
                            ),
                          ],
                        ),
                        isThreeLine: true,
                      ),
                  ],
                ]),
                _section('My library', Icons.bookmarks_rounded, [
                  if (!api.isAuthenticated)
                    const Text('Sign in to save favorites and recent apps.')
                  else ...[
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${_library.length} saved or recently opened apps',
                          ),
                        ),
                        IconButton(
                          tooltip: 'Refresh library',
                          onPressed: _busy ? null : _loadLibrary,
                          icon: const Icon(Icons.refresh_rounded),
                        ),
                      ],
                    ),
                    if (_library.isEmpty)
                      const Text(
                        'Bookmark apps from the catalog to build your library.',
                      )
                    else
                      for (final app in _library)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(app['name']?.toString() ?? 'App'),
                          subtitle: Text(
                            [
                              if (app['favorited_at'] != null) 'Favorite',
                              if (app['last_opened_at'] != null)
                                'Recently opened',
                              app['license']?.toString() ?? '',
                            ].where((value) => value.isNotEmpty).join(' · '),
                          ),
                          leading: const Icon(Icons.android_rounded),
                          trailing: IconButton(
                            tooltip: _favoriteIds.contains(app['id'].toString())
                                ? 'Remove favorite'
                                : 'Add to favorites',
                            onPressed: _busy
                                ? null
                                : () => _toggleFavorite(app),
                            icon: Icon(
                              _favoriteIds.contains(app['id'].toString())
                                  ? Icons.bookmark_remove_outlined
                                  : Icons.bookmark_add_outlined,
                            ),
                          ),
                          onTap: _busy
                              ? null
                              : () async {
                                  await _api!.configureBaseUrl(
                                    _baseUrlController.text,
                                  );
                                  await _api!.recordAppOpened(
                                    app['id'].toString(),
                                  );
                                  await _loadCachedInspection(
                                    app['id'].toString(),
                                    app['name']?.toString() ?? 'app',
                                  );
                                },
                        ),
                  ],
                ]),
                _section('Remix Studio', Icons.auto_awesome_rounded, [
                  if (!api.isAuthenticated)
                    const Text(
                      'Sign in to create and continue your private remix sessions.',
                    )
                  else ...[
                    Row(
                      children: [
                        const Expanded(child: Text('Your planning sessions')),
                        IconButton(
                          tooltip: 'Refresh remix sessions',
                          onPressed: _busy ? null : _loadRemixSessions,
                          icon: const Icon(Icons.refresh_rounded),
                        ),
                      ],
                    ),
                    if (_remixSessions.isEmpty)
                      const Text(
                        'No remix sessions loaded. Start one from a catalog search result, or refresh this list.',
                      )
                    else
                      for (final remix in _remixSessions)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          selected: _activeRemix?['id'] == remix['id'],
                          leading: const Icon(Icons.edit_note_rounded),
                          title: Text(
                            remix['title']?.toString() ?? 'Untitled remix',
                          ),
                          subtitle: Text(
                            '${remix['app_name'] ?? 'App'} · ${(remix['source_commit_sha']?.toString() ?? '').substring(0, (remix['source_commit_sha']?.toString() ?? '').length.clamp(0, 10))}',
                          ),
                          trailing: const Icon(Icons.chevron_right_rounded),
                          onTap: _busy
                              ? null
                              : () => _openRemix(remix['id'].toString()),
                        ),
                    if (_activeRemix case final active?) ...[
                      const Divider(height: 24),
                      Text(
                        active['title']?.toString() ?? 'Active remix',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(
                        '${active['app_name'] ?? 'App'} · pinned to ${active['source_commit_sha'] ?? 'unknown commit'}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          const Expanded(child: Text('Indexed source files')),
                          Text(
                            '$_repositoryFileTotal files · ${_selectedSourcePaths.length} selected',
                          ),
                          IconButton(
                            tooltip: 'Load indexed source files',
                            onPressed: _busy ? null : _loadRemixFiles,
                            icon: const Icon(Icons.folder_open_rounded),
                          ),
                        ],
                      ),
                      _textField(
                        _fileQueryController,
                        'Filter source paths',
                        hint: 'MainActivity, AndroidManifest, build.gradle',
                      ),
                      if (_repositoryFiles.isNotEmpty) ...[
                        for (final file in _repositoryFiles)
                          ExpansionTile(
                            tilePadding: EdgeInsets.zero,
                            leading: Checkbox(
                              value: _selectedSourcePaths.contains(
                                file['path']?.toString() ?? '',
                              ),
                              onChanged: _busy
                                  ? null
                                  : (selected) {
                                      final path =
                                          file['path']?.toString() ?? '';
                                      setState(() {
                                        if (selected == true) {
                                          _selectedSourcePaths.add(path);
                                        } else {
                                          _selectedSourcePaths.remove(path);
                                        }
                                      });
                                    },
                            ),
                            title: Text(
                              file['path']?.toString() ?? 'Source file',
                            ),
                            subtitle: Text(
                              '${file['language'] ?? 'source'} · ${file['content_sha']?.toString().substring(0, 10) ?? 'unknown'}',
                            ),
                            children: [
                              SelectableText(
                                file['content_excerpt']?.toString() ?? '',
                                style: const TextStyle(
                                  fontFamily: 'monospace',
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                      ],
                      const SizedBox(height: 12),
                      for (final message
                          in (active['messages'] as List? ?? const []))
                        Padding(
                          padding: const EdgeInsets.only(bottom: 14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Icon(
                                    message['role'] == 'assistant'
                                        ? Icons.auto_awesome
                                        : Icons.person_outline,
                                    size: 18,
                                  ),
                                  const SizedBox(width: 8),
                                  Text(
                                    message['role'] == 'assistant'
                                        ? 'VibeStore plan'
                                        : 'You',
                                    style: Theme.of(
                                      context,
                                    ).textTheme.labelLarge,
                                  ),
                                  const Spacer(),
                                  if (message['message_type'] == 'change_plan')
                                    const Chip(label: Text('Plan')),
                                ],
                              ),
                              const SizedBox(height: 6),
                              SelectableText(
                                message['content']?.toString() ?? '',
                              ),
                              if ((message['evidence'] as List? ?? const [])
                                  .isNotEmpty) ...[
                                const SizedBox(height: 6),
                                Text(
                                  'Evidence: ${(message['evidence'] as List).map((item) => item is Map ? item['path'] : '').where((path) => path.toString().isNotEmpty).join(', ')}',
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ],
                            ],
                          ),
                        ),
                      const Divider(height: 24),
                      Row(
                        children: [
                          const Expanded(
                            child: Text('Reviewable patch drafts'),
                          ),
                          IconButton(
                            tooltip: 'Refresh patch proposals',
                            onPressed: _busy
                                ? null
                                : () => _run(() async {
                                    final proposals = await _api!
                                        .remixPatchProposals(
                                          active['id'].toString(),
                                        );
                                    if (mounted) {
                                      setState(
                                        () => _remixProposals = proposals,
                                      );
                                    }
                                  }),
                            icon: const Icon(Icons.refresh_rounded),
                          ),
                        ],
                      ),
                      if (_remixProposals.isEmpty)
                        const Text(
                          'No patch drafts yet. Generate one after describing a change.',
                        )
                      else
                        for (final proposal in _remixProposals) ...[
                          Card(
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Expanded(
                                        child: Text(
                                          proposal['summary']?.toString() ??
                                              'Patch proposal',
                                          style: Theme.of(
                                            context,
                                          ).textTheme.titleSmall,
                                        ),
                                      ),
                                      Chip(
                                        label: Text(
                                          proposal['status']?.toString() ??
                                              'proposed',
                                        ),
                                      ),
                                    ],
                                  ),
                                  Text(
                                    'Base commit: ${proposal['base_commit_sha'] ?? 'unknown'}',
                                    style: Theme.of(
                                      context,
                                    ).textTheme.bodySmall,
                                  ),
                                  Text(
                                    'Source validation · ${proposal['validation_status'] ?? 'review_only'} · approval never applies changes',
                                    style: Theme.of(
                                      context,
                                    ).textTheme.bodySmall,
                                  ),

                                  if ((proposal['validation_report']
                                          as Map?)?['message'] !=
                                      null) ...[
                                    Text(
                                      'Validation: ${(proposal['validation_report'] as Map)['message']}',
                                      style: Theme.of(
                                        context,
                                      ).textTheme.bodySmall,
                                    ),
                                    for (final verified
                                        in ((proposal['validation_report']
                                                    as Map?)?['files']
                                                as List? ??
                                            const []))
                                      Text(
                                        'Verified ${verified['path']} · result SHA-256 ${verified['result_sha256']}',
                                        style: Theme.of(
                                          context,
                                        ).textTheme.bodySmall,
                                      ),
                                  ],
                                  if (((proposal['proposal'] as Map?)?['risks']
                                              as List? ??
                                          const [])
                                      .isNotEmpty) ...[
                                    Text(
                                      'Risks',
                                      style: Theme.of(
                                        context,
                                      ).textTheme.labelLarge,
                                    ),
                                    for (final risk
                                        in ((proposal['proposal']
                                                    as Map?)?['risks']
                                                as List? ??
                                            const []))
                                      Text('• $risk'),
                                  ],
                                  if (((proposal['proposal']
                                                  as Map?)?['validation_steps']
                                              as List? ??
                                          const [])
                                      .isNotEmpty) ...[
                                    Text(
                                      'Validation steps',
                                      style: Theme.of(
                                        context,
                                      ).textTheme.labelLarge,
                                    ),
                                    for (final step
                                        in ((proposal['proposal']
                                                    as Map?)?['validation_steps']
                                                as List? ??
                                            const []))
                                      Text('• $step'),
                                  ],
                                  for (final file
                                      in ((proposal['proposal']
                                                  as Map?)?['files']
                                              as List? ??
                                          const []))
                                    ExpansionTile(
                                      tilePadding: EdgeInsets.zero,
                                      title: Text(
                                        file['path']?.toString() ??
                                            'Source file',
                                      ),
                                      subtitle: Text(
                                        file['rationale']?.toString() ?? '',
                                      ),
                                      children: [
                                        SelectableText(
                                          file['diff']?.toString() ?? '',
                                          style: const TextStyle(
                                            fontFamily: 'monospace',
                                            fontSize: 12,
                                          ),
                                        ),
                                      ],
                                    ),
                                  if (proposal['status'] == 'approved')
                                    Align(
                                      alignment: Alignment.centerLeft,
                                      child: OutlinedButton.icon(
                                        onPressed: _busy
                                            ? null
                                            : () => _processApprovedProposal(
                                                proposal['id'].toString(),
                                              ),
                                        icon: const Icon(
                                          Icons.archive_outlined,
                                        ),
                                        label: const Text('Prepare source ZIP'),
                                      ),
                                    ),
                                  if (proposal['status'] == 'proposed')
                                    Wrap(
                                      spacing: 8,
                                      children: [
                                        if (proposal['validation_status'] !=
                                            'applicable')
                                          OutlinedButton.icon(
                                            onPressed: _busy
                                                ? null
                                                : () => _validatePatchProposal(
                                                    proposal['id'].toString(),
                                                  ),
                                            icon: const Icon(
                                              Icons.verified_outlined,
                                            ),
                                            label: const Text(
                                              'Verify against source',
                                            ),
                                          ),
                                        if (proposal['validation_status'] ==
                                            'applicable')
                                          OutlinedButton.icon(
                                            onPressed: _busy
                                                ? null
                                                : () => _reviewPatchProposal(
                                                    proposal['id'].toString(),
                                                    'approved',
                                                  ),
                                            icon: const Icon(
                                              Icons.check_circle_outline,
                                            ),
                                            label: const Text(
                                              'Approve proposal',
                                            ),
                                          ),
                                        TextButton.icon(
                                          onPressed: _busy
                                              ? null
                                              : () => _reviewPatchProposal(
                                                  proposal['id'].toString(),
                                                  'rejected',
                                                ),
                                          icon: const Icon(
                                            Icons.cancel_outlined,
                                          ),
                                          label: const Text('Reject'),
                                        ),
                                      ],
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      TextField(
                        controller: _remixPromptController,
                        minLines: 2,
                        maxLines: 5,
                        maxLength: 4000,
                        decoration: const InputDecoration(
                          labelText: 'Describe the change you want',
                          hintText:
                              'Add biometric unlock, redesign the settings screen…',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      Wrap(
                        alignment: WrapAlignment.end,
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          if (_supportsPatchRemix(active))
                            OutlinedButton.icon(
                              onPressed: _busy ? null : _generatePatchProposal,
                              icon: const Icon(Icons.difference_outlined),
                              label: const Text('Draft source diff'),
                            ),
                          FilledButton.icon(
                            onPressed: _busy ? null : _sendRemixMessage,
                            icon: const Icon(Icons.auto_awesome_rounded),
                            label: const Text('Generate change plan'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _supportsPatchRemix(active)
                            ? 'Patch drafts are review-only. Approving records your decision; it does not edit files or run a build.'
                            : 'AI change plans are available for this source. Source patch generation is currently limited to GitHub repositories.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Approved diffs can be materialized into a review-only changed-source ZIP. This is not a complete checkout and does not run Gradle or produce an APK.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ],
                ]),
                _section(
                  'Inspect or index a repository',
                  Icons.manage_search_rounded,
                  [
                    _textField(
                      _repositoryController,
                      'Public repository URL',
                      hint: 'GitHub, GitLab.com or Codeberg repository URL',
                      keyboardType: TextInputType.url,
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        FilledButton.tonal(
                          onPressed: _busy || !api.isAuthenticated
                              ? null
                              : _indexRepository,
                          child: const Text('Index repository'),
                        ),
                        OutlinedButton(
                          onPressed: _busy ? null : _inspectRepository,
                          child: const Text('Inspect repository'),
                        ),
                      ],
                    ),
                    if (_inspection != null) ...[
                      const Divider(height: 24),
                      SelectableText(
                        _inspection!,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          fontFamily: 'monospace',
                        ),
                      ),
                    ],
                  ],
                ),
                if (_busy) const LinearProgressIndicator(),
                if (_notice != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      _notice!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                  ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}
