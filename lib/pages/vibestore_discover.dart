import 'dart:convert';

import 'package:material_ui/material_ui.dart';
import 'package:obtainium/services/vibestore_api.dart';

class VibeStoreDiscoverPage extends StatefulWidget {
  const VibeStoreDiscoverPage({super.key});

  @override
  State<VibeStoreDiscoverPage> createState() => _VibeStoreDiscoverPageState();
}

class _VibeStoreDiscoverPageState extends State<VibeStoreDiscoverPage> {
  final _baseUrlController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _queryController = TextEditingController();
  final _repositoryController = TextEditingController();

  VibeStoreApi? _api;
  List<Map<String, dynamic>> _results = [];
  List<Map<String, dynamic>> _submissions = [];
  String? _inspection;
  String? _notice;
  String? _error;
  bool _initializing = true;
  bool _busy = false;

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
    _repositoryController.dispose();
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

  Future<void> _search() => _run(() async {
    await _api!.configureBaseUrl(_baseUrlController.text);
    final results = await _api!.search(_queryController.text);
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
    await _api!.configureBaseUrl(_baseUrlController.text);
    final result = await _api!.indexRepository(_repositoryController.text);
    final repositories = await _api!.myRepositories();
    if (!mounted) return;
    setState(() {
      _submissions = repositories;
      _notice =
          'Indexed ${result['name']} (${result['indexed_files']} source files).';
    });
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

  Future<void> _logout() async {
    _api?.logout();
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
        appBar: AppBar(title: const Text('VibeStore discovery')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    final api = _api;
    return Scaffold(
      appBar: AppBar(
        title: const Text('VibeStore discovery'),
        actions: [
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
                        : 'Sign in to submit repositories. Your access token stays in memory and is not written to preferences.',
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
                _section('Discover apps', Icons.travel_explore_rounded, [
                  _textField(
                    _queryController,
                    'Describe what you are looking for',
                    hint: 'A private notes app with offline sync',
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
                        title: Text(
                          result['name']?.toString() ?? 'Unnamed app',
                        ),
                        subtitle: Text(
                          [
                            result['description']?.toString() ?? '',
                            result['repository_url']?.toString() ?? '',
                          ].where((value) => value.isNotEmpty).join('\n'),
                        ),
                        trailing: Text(
                          (result['score'] as num?)?.toStringAsFixed(2) ?? '',
                        ),
                        isThreeLine: true,
                      ),
                  ],
                ]),
                _section(
                  'Inspect or index a repository',
                  Icons.manage_search_rounded,
                  [
                    _textField(
                      _repositoryController,
                      'Public GitHub repository URL',
                      hint: 'https://github.com/owner/repository',
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
