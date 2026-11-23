import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class VibeStoreApiException implements Exception {
  const VibeStoreApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class VibeStoreApi {
  VibeStoreApi._({
    required SharedPreferences preferences,
    required http.Client client,
    required String baseUrl,
    required String? accessToken,
  }) : _preferences = preferences,
       _client = client,
       _baseUrl = baseUrl,
       _accessToken = accessToken;

  static const _baseUrlKey = 'vibestore.api.baseUrl';
  static const _timeout = Duration(seconds: 30);

  final SharedPreferences _preferences;
  final http.Client _client;
  String _baseUrl;
  String? _accessToken;

  String get baseUrl => _baseUrl;
  bool get isAuthenticated => _accessToken != null;

  static Future<VibeStoreApi> load() async {
    final preferences = await SharedPreferences.getInstance();
    return VibeStoreApi._(
      preferences: preferences,
      client: http.Client(),
      baseUrl: preferences.getString(_baseUrlKey) ?? '',
      accessToken: null,
    );
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
    if (uri.scheme != 'https' && !(uri.scheme == 'http' && isLocal && !kReleaseMode)) {
      throw const VibeStoreApiException(
        'HTTPS is required. HTTP is allowed only for local debug development.',
      );
    }

    if (normalized != _baseUrl) {
      _accessToken = null;
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

  Future<List<Map<String, dynamic>>> search(String query, {int limit = 20}) async {
    final response = await _post('search', {'query': query, 'limit': limit});
    final items = response['items'];
    if (items is! List) {
      throw const VibeStoreApiException('The search response was invalid.');
    }
    return items
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> indexRepository(String repositoryUrl) =>
      _post('repositories/index', {'repository_url': repositoryUrl.trim()});

  Future<Map<String, dynamic>> inspectRepository(String repositoryUrl) =>
      _post('repositories/inspect', {'repository_url': repositoryUrl.trim()});

  Future<void> logout() async {
    _accessToken = null;
  }

  Future<void> _saveToken(Map<String, dynamic> response) async {
    final token = response['access_token'];
    if (token is! String || token.isEmpty) {
      throw const VibeStoreApiException('The API returned an invalid access token.');
    }
    _accessToken = token;
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> payload,
  ) async {
    if (_baseUrl.isEmpty) {
      throw const VibeStoreApiException('Configure the VibeStore API address first.');
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
        .timeout(_timeout);
    dynamic decoded;
    try {
      decoded = jsonDecode(response.body);
    } on FormatException {
      decoded = null;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw VibeStoreApiException(
        detail is String ? detail : 'VibeStore API request failed (${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    if (decoded is List) {
      return {'items': decoded};
    }
    if (decoded is! Map<String, dynamic>) {
      throw const VibeStoreApiException('The VibeStore API returned an invalid response.');
    }
    return decoded;
  }

  void dispose() => _client.close();
}
