import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class VibeStoreApiException implements Exception {
  const VibeStoreApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class VibeStoreApi {
  VibeStoreApi._({
    required this._preferences,
    required this._secureStorage,
    required this._client,
    required this._baseUrl,
  });

  static const _baseUrlKey = 'vibestore.api.baseUrl';
  static const _accessTokenKey = 'vibestore.auth.accessToken';
  static const _timeout = Duration(seconds: 30);

  final SharedPreferences _preferences;
  final FlutterSecureStorage _secureStorage;
  final http.Client _client;
  String _baseUrl;
  String? _accessToken;

  String get baseUrl => _baseUrl;
  bool get isAuthenticated => _accessToken != null;

  static Future<VibeStoreApi> load() async {
    final preferences = await SharedPreferences.getInstance();
    const secureStorage = FlutterSecureStorage();
    final accessToken = await secureStorage.read(key: _accessTokenKey);
    return VibeStoreApi._(
      preferences: preferences,
      secureStorage: secureStorage,
      client: http.Client(),
      baseUrl: preferences.getString(_baseUrlKey) ?? '',
    ).._accessToken = accessToken;
  }

  Future<void> configureBaseUrl(String value) async {
    final normalized = value.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(normalized);
    if (uri == null ||
        !uri.hasAuthority ||
        uri.host.isEmpty ||
        uri.path.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const VibeStoreApiException(
        'Enter an API origin such as https://api.example.com.',
      );
    }

    final isLocal = const {
      'localhost',
      '127.0.0.1',
      '10.0.2.2',
    }.contains(uri.host);
    if (uri.scheme != 'https' &&
        !(uri.scheme == 'http' && isLocal && !kReleaseMode)) {
      throw const VibeStoreApiException(
        'HTTPS is required. HTTP is allowed only for local debug development.',
      );
    }

    if (normalized != _baseUrl) {
      _accessToken = null;
      await _secureStorage.delete(key: _accessTokenKey);
    }
    _baseUrl = normalized;
    await _preferences.setString(_baseUrlKey, normalized);
  }

  Future<Map<String, dynamic>> register(String email, String password) async {
    final response = await _post('auth/register', {
      'email': email.trim(),
      'password': password,
    });
    await _saveToken(response);
    return Map<String, dynamic>.from(response['user'] as Map);
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final response = await _post('auth/token', {
      'email': email.trim(),
      'password': password,
    });
    await _saveToken(response);
    return Map<String, dynamic>.from(response['user'] as Map);
  }

  Future<Map<String, dynamic>> catalog({
    String? query,
    String sort = 'popular',
    int limit = 24,
    int offset = 0,
  }) async {
    final parameters = <String, String>{
      'sort': sort,
      'limit': '$limit',
      'offset': '$offset',
      if (query != null && query.trim().isNotEmpty) 'query': query.trim(),
    };
    final response = await _get(
      'catalog?${Uri(queryParameters: parameters).query}',
    );
    if (response is! Map<String, dynamic> || response['items'] is! List) {
      throw const VibeStoreApiException('The catalog response was invalid.');
    }
    return response;
  }

  Future<List<Map<String, dynamic>>> search(
    String query, {
    int limit = 20,
    String? license,
    int? minStars,
  }) async {
    final response = await _post('search', {
      'query': query,
      'limit': limit,
      'license': license,
      'min_stars': minStars,
    });
    final items = response['items'];
    if (items is! List) {
      throw const VibeStoreApiException('The search response was invalid.');
    }
    return items
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(growable: false);
  }

  Future<List<Map<String, dynamic>>> myRepositories() async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .get(
          Uri.parse('$_baseUrl/api/v1/repositories/mine'),
          headers: _authorizedHeaders(),
        )
        .timeout(_timeout);
    final decoded = _decodeResponse(response);
    if (decoded is! List) {
      throw const VibeStoreApiException(
        'The repository collection response was invalid.',
      );
    }
    return decoded
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(growable: false);
  }

  Future<void> removeMyRepository(String appId) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .delete(
          Uri.parse('$_baseUrl/api/v1/repositories/mine/$appId'),
          headers: _authorizedHeaders(),
        )
        .timeout(_timeout);
    if (response.statusCode == 204) return;
    _decodeResponse(response);
  }

  Map<String, String> _authorizedHeaders() {
    final headers = <String, String>{'Accept': 'application/json'};
    if (_accessToken case final token?) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  dynamic _decodeResponse(http.Response response) {
    dynamic decoded;
    try {
      decoded = response.body.isEmpty ? null : jsonDecode(response.body);
    } on FormatException {
      decoded = null;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw VibeStoreApiException(
        detail is String
            ? detail
            : 'VibeStore API request failed (${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    return decoded;
  }

  Future<Map<String, dynamic>> enqueueRepositoryIndex(String repositoryUrl) =>
      _post('repositories/index-jobs', {
        'repository_url': repositoryUrl.trim(),
      });

  Future<Map<String, dynamic>> repositoryIndexJob(String jobId) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .get(
          Uri.parse('$_baseUrl/api/v1/repositories/jobs/$jobId'),
          headers: _authorizedHeaders(),
        )
        .timeout(_timeout);
    final decoded = _decodeResponse(response);
    if (decoded is! Map<String, dynamic>) {
      throw const VibeStoreApiException(
        'The indexing job response was invalid.',
      );
    }
    return decoded;
  }

  Future<Map<String, dynamic>> repositoryFiles(
    String appId, {
    String? query,
    int limit = 50,
    int offset = 0,
  }) async {
    final parameters = <String, String>{
      'limit': '$limit',
      'offset': '$offset',
      if (query != null && query.trim().isNotEmpty) 'query': query.trim(),
    };
    final response = await _get(
      'apps/$appId/files?${Uri(queryParameters: parameters).query}',
    );
    if (response is! Map<String, dynamic> || response['items'] is! List) {
      throw const VibeStoreApiException(
        'The repository file response was invalid.',
      );
    }
    return response;
  }

  Future<Map<String, dynamic>> cachedInspection(String appId) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .get(
          Uri.parse('$_baseUrl/api/v1/apps/$appId/inspection'),
          headers: _authorizedHeaders(),
        )
        .timeout(_timeout);
    final decoded = _decodeResponse(response);
    if (decoded is! Map<String, dynamic>) {
      throw const VibeStoreApiException(
        'The cached inspection response was invalid.',
      );
    }
    return decoded;
  }

  Future<List<Map<String, dynamic>>> remixSessions() async {
    final response = await _get('remixes');
    if (response is! List) {
      throw const VibeStoreApiException(
        'The remix session response was invalid.',
      );
    }
    return response
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> createRemixSession(
    String appId, {
    String title = 'New remix',
  }) => _post('remixes', {'app_id': appId, 'title': title});

  Future<Map<String, dynamic>> remixSession(String remixId) async {
    final response = await _get('remixes/$remixId');
    if (response is! Map<String, dynamic>) {
      throw const VibeStoreApiException(
        'The remix session response was invalid.',
      );
    }
    return response;
  }

  Future<Map<String, dynamic>> sendRemixMessage(
    String remixId,
    String content,
  ) => _post('remixes/$remixId/messages', {
    'content': content.trim(),
  }, timeout: const Duration(seconds: 110));

  Future<List<Map<String, dynamic>>> remixPatchProposals(String remixId) async {
    final response = await _get('remixes/$remixId/proposals');
    if (response is! List) {
      throw const VibeStoreApiException(
        'The remix proposal response was invalid.',
      );
    }
    return response
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> generateRemixPatchProposal(
    String remixId,
    String content,
  ) => _post('remixes/$remixId/proposals', {
    'content': content.trim(),
  }, timeout: const Duration(seconds: 110));

  Future<Map<String, dynamic>> validateRemixPatchProposal(
    String remixId,
    String proposalId,
  ) => _post(
    'remixes/$remixId/proposals/$proposalId/validate',
    const {},
    timeout: const Duration(seconds: 110),
  );

  Future<Map<String, dynamic>> reviewRemixPatchProposal(
    String remixId,
    String proposalId,
    String decision,
  ) => _post('remixes/$remixId/proposals/$proposalId/review', {
    'decision': decision,
  });

  Future<Map<String, dynamic>> processApprovedPatch(
    String remixId,
    String proposalId,
  ) => _post(
    'remixes/$remixId/proposals/$proposalId/process',
    const {},
    timeout: const Duration(seconds: 60),
  );

  Future<http.Response> patchArtifact(String remixId, String proposalId) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .get(
          Uri.parse(
            '$_baseUrl/api/v1/remixes/$remixId/proposals/$proposalId/artifact',
          ),
          headers: _authorizedHeaders(),
        )
        .timeout(_timeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      dynamic decoded;
      try {
        decoded = jsonDecode(response.body);
      } on FormatException {
        decoded = null;
      }
      final detail = decoded is Map ? decoded['detail'] : null;
      throw VibeStoreApiException(
        detail is String
            ? detail
            : 'Patch artifact request failed (${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    return response;
  }

  Future<dynamic> _get(String path) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final response = await _client
        .get(Uri.parse('$_baseUrl/api/v1/$path'), headers: _authorizedHeaders())
        .timeout(_timeout);
    return _decodeResponse(response);
  }

  Future<Map<String, dynamic>> indexRepository(String repositoryUrl) =>
      _post('repositories/index', {'repository_url': repositoryUrl.trim()});

  Future<Map<String, dynamic>> inspectRepository(String repositoryUrl) =>
      _post('repositories/inspect', {'repository_url': repositoryUrl.trim()});

  Future<void> logout() async {
    _accessToken = null;
    await _secureStorage.delete(key: _accessTokenKey);
  }

  Future<void> _saveToken(Map<String, dynamic> response) async {
    final token = response['access_token'];
    if (token is! String || token.isEmpty) {
      throw const VibeStoreApiException(
        'The API returned an invalid access token.',
      );
    }
    _accessToken = token;
    await _secureStorage.write(key: _accessTokenKey, value: token);
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> payload, {
    Duration timeout = _timeout,
  }) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException(
        'Configure the VibeStore API address first.',
      );
    }
    final headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    };
    if (_accessToken case final token?) {
      headers['Authorization'] = 'Bearer $token';
    }

    final response = await _client
        .post(
          Uri.parse('$_baseUrl/api/v1/$path'),
          headers: headers,
          body: jsonEncode(payload),
        )
        .timeout(timeout);
    dynamic decoded;
    try {
      decoded = jsonDecode(response.body);
    } on FormatException {
      decoded = null;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw VibeStoreApiException(
        detail is String
            ? detail
            : 'VibeStore API request failed (${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    if (decoded is List) {
      return {'items': decoded};
    }
    if (decoded is! Map<String, dynamic>) {
      throw const VibeStoreApiException(
        'The VibeStore API returned an invalid response.',
      );
    }
    return decoded;
  }

  void dispose() => _client.close();
}
