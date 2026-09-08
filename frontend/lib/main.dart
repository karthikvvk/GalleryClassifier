// Image Classifier — single-page Flutter frontend.
//
// Tabs:
//   - "Explorer"   : browse the real local filesystem (details / icon view)
//   - "Classified" : shows the 4 output classes (screenshot, memes, wallpaper, photos)
//
// Backend contract:
//   POST {backendBaseUrl}/runclassification
//     body: { "path": "<currentPath>" }
//     response: {
//       "screenshot": { "count": 120, "size_bytes": 543210 },
//       "memes":      { "count": 40,  "size_bytes": 123456 },
//       "wallpaper":  { "count": 12,  "size_bytes": 987654 },
//       "photos":     { "count": 300, "size_bytes": 5432100 }
//     }

import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

const String backendBaseUrl = 'http://localhost:8000';

void main() {
  runApp(const ImageClassifierApp());
}

// ---------------------------------------------------------------------------
// App root — Material 3 dark theme
// ---------------------------------------------------------------------------
class ImageClassifierApp extends StatelessWidget {
  const ImageClassifierApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Image Classifier',
      debugShowCheckedModeBanner: false,
      themeMode: ThemeMode.dark,
      darkTheme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2E86FF),
          brightness: Brightness.dark,
        ),
        fontFamily: 'Roboto',
        inputDecorationTheme: const InputDecorationTheme(
          border: InputBorder.none,
          isDense: true,
        ),
        dividerTheme: const DividerThemeData(
          color: Color(0xFF2E2E2E),
          thickness: 1,
        ),
      ),
      home: const HomePage(),
    );
  }
}

// ---------------------------------------------------------------------------
// Enums & data models
// ---------------------------------------------------------------------------
enum AppTab { explorer, classified }

enum ViewMode { details, icons }

class ClassifiedClass {
  final String key;
  final String label;
  final IconData icon;
  int fileCount;
  int sizeBytes;

  ClassifiedClass(this.key, this.label, this.icon,
      {this.fileCount = 0, this.sizeBytes = 0});
}

class _FsItem {
  final String name;
  final bool isDir;
  const _FsItem({required this.name, required this.isDir});
}

// ---------------------------------------------------------------------------
// Home page
// ---------------------------------------------------------------------------
class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  AppTab _tab = AppTab.explorer;
  ViewMode _viewMode = ViewMode.details;
  bool _isRunning = false;
  bool _isLoadingDir = false;
  int? _selectedClassIdx;

  final _pathCtrl = TextEditingController(text: '/home/muruga/');

  final List<ClassifiedClass> _classes = [
    ClassifiedClass('screenshot', 'Screenshots', Icons.screenshot_monitor),
    ClassifiedClass('memes', 'Memes', Icons.sentiment_very_satisfied),
    ClassifiedClass('wallpaper', 'Wallpapers', Icons.wallpaper),
    ClassifiedClass('photos', 'Photos', Icons.photo_library),
  ];

  List<_FsItem> _dirItems = [];

  @override
  void initState() {
    super.initState();
    _loadDir(_pathCtrl.text);
  }

  @override
  void dispose() {
    _pathCtrl.dispose();
    super.dispose();
  }

  // -- Filesystem listing via dart:io ----------------------------------------
  Future<void> _loadDir(String path) async {
    setState(() => _isLoadingDir = true);
    try {
      final dir = Directory(path);
      final entries = await dir
          .list(followLinks: false)
          .where((e) => !e.path.split('/').last.startsWith('.'))
          .toList();

      entries.sort((a, b) {
        final aDir = a is Directory;
        final bDir = b is Directory;
        if (aDir != bDir) return aDir ? -1 : 1;
        return a.path.split('/').last
            .toLowerCase()
            .compareTo(b.path.split('/').last.toLowerCase());
      });

      if (mounted) {
        setState(() {
          _dirItems = entries
              .map((e) => _FsItem(
                    name: e.path.split('/').last,
                    isDir: e is Directory,
                  ))
              .toList();
        });
      }
    } catch (e) {
      if (mounted) _snack('Cannot open directory: $e');
    } finally {
      if (mounted) setState(() => _isLoadingDir = false);
    }
  }

  void _navigateTo(String path) {
    final trimmed = path.endsWith('/') ? path : '$path/';
    _pathCtrl.text = trimmed;
    _loadDir(trimmed);
  }

  void _navigateUp() {
    final parts = _pathCtrl.text.trimRight().split('/')
      ..removeWhere((p) => p.isEmpty);
    if (parts.isEmpty) return;
    parts.removeLast();
    final parent = parts.isEmpty ? '/' : '/${parts.join('/')}/';
    _navigateTo(parent);
  }

  // -- Classification via backend --------------------------------------------
  Future<void> _runClassification() async {
    setState(() => _isRunning = true);
    try {
      final uri = Uri.parse('$backendBaseUrl/runclassification');
      final response = await http.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'path': _pathCtrl.text.trim()}),
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        setState(() {
          for (final c in _classes) {
            final entry = data[c.key] as Map<String, dynamic>?;
            if (entry != null) {
              c.fileCount = (entry['count'] as num?)?.toInt() ?? c.fileCount;
              c.sizeBytes =
                  (entry['size_bytes'] as num?)?.toInt() ?? c.sizeBytes;
            }
          }
        });
        _snack('Classification complete!');
      } else {
        _snack('Classification failed (HTTP ${response.statusCode})');
      }
    } catch (e) {
      _snack('Could not reach backend: $e');
    } finally {
      if (mounted) setState(() => _isRunning = false);
    }
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(msg)));
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: cs.surface,
      body: Column(
        children: [
          _buildTopBar(cs),
          _buildPathBar(cs),
          const Divider(height: 1),
          Expanded(child: _buildContent()),
          _buildStatusBar(cs),
        ],
      ),
    );
  }

  // -- Top bar ---------------------------------------------------------------
  Widget _buildTopBar(ColorScheme cs) {
    return Container(
      height: 56,
      color: cs.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        children: [
          // Tab toggle
          _TabPill(
            label: 'Explorer',
            icon: Icons.folder_open,
            selected: _tab == AppTab.explorer,
            onTap: () => setState(() {
              _tab = AppTab.explorer;
              _selectedClassIdx = null;
            }),
          ),
          const SizedBox(width: 8),
          _TabPill(
            label: 'Classified',
            icon: Icons.category_outlined,
            selected: _tab == AppTab.classified,
            onTap: () => setState(() {
              _tab = AppTab.classified;
              _selectedClassIdx = null;
            }),
          ),
          const Spacer(),
          // View mode toggle
          IconButton(
            icon: const Icon(Icons.view_list_rounded),
            tooltip: 'Details view',
            isSelected: _viewMode == ViewMode.details,
            selectedIcon: Icon(Icons.view_list_rounded, color: cs.primary),
            onPressed: () => setState(() => _viewMode = ViewMode.details),
          ),
          IconButton(
            icon: const Icon(Icons.grid_view_rounded),
            tooltip: 'Icon view',
            isSelected: _viewMode == ViewMode.icons,
            selectedIcon: Icon(Icons.grid_view_rounded, color: cs.primary),
            onPressed: () => setState(() => _viewMode = ViewMode.icons),
          ),
          const SizedBox(width: 8),
          const VerticalDivider(width: 1, indent: 12, endIndent: 12),
          const SizedBox(width: 8),
          // Run button
          FilledButton.icon(
            onPressed: _isRunning ? null : _runClassification,
            icon: _isRunning
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow_rounded),
            label: Text(_isRunning ? 'Running…' : 'Run'),
          ),
        ],
      ),
    );
  }

  // -- Path bar ---------------------------------------------------------------
  Widget _buildPathBar(ColorScheme cs) {
    return Container(
      height: 40,
      color: cs.surfaceContainer,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.arrow_upward, size: 18),
            tooltip: 'Go up',
            onPressed: _navigateUp,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, size: 18),
            tooltip: 'Refresh',
            onPressed: () => _loadDir(_pathCtrl.text),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: TextField(
              controller: _pathCtrl,
              style: Theme.of(context).textTheme.bodyMedium,
              decoration: const InputDecoration(
                isDense: true,
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                border: InputBorder.none,
              ),
              onSubmitted: _navigateTo,
            ),
          ),
          if (_isLoadingDir)
            const Padding(
              padding: EdgeInsets.only(right: 8),
              child: SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
        ],
      ),
    );
  }

  // -- Main content ----------------------------------------------------------
  Widget _buildContent() {
    if (_tab == AppTab.explorer) {
      return _viewMode == ViewMode.details
          ? _buildExplorerList()
          : _buildExplorerGrid();
    }
    return _viewMode == ViewMode.details
        ? _buildClassifiedList()
        : _buildClassifiedGrid();
  }

  // -- Explorer list view ----------------------------------------------------
  Widget _buildExplorerList() {
    if (_isLoadingDir) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_dirItems.isEmpty) {
      return const Center(child: Text('Empty directory'));
    }
    return ListView.builder(
      itemCount: _dirItems.length,
      itemExtent: 40,
      itemBuilder: (ctx, i) {
        final item = _dirItems[i];
        return InkWell(
          onTap: item.isDir
              ? () => _navigateTo('${_pathCtrl.text}${item.name}')
              : null,
          child: Padding(
            padding:
                const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Icon(
                  item.isDir ? Icons.folder : Icons.insert_drive_file_outlined,
                  size: 18,
                  color: item.isDir
                      ? const Color(0xFFDD8D2B)
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    item.name,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  // -- Explorer icon/grid view -----------------------------------------------
  Widget _buildExplorerGrid() {
    if (_isLoadingDir) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_dirItems.isEmpty) {
      return const Center(child: Text('Empty directory'));
    }
    return GridView.builder(
      padding: const EdgeInsets.all(12),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 90,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: 0.75,
      ),
      itemCount: _dirItems.length,
      itemBuilder: (ctx, i) {
        final item = _dirItems[i];
        return InkWell(
          onTap: item.isDir
              ? () => _navigateTo('${_pathCtrl.text}${item.name}')
              : null,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.all(4),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  item.isDir ? Icons.folder_rounded : Icons.image_outlined,
                  size: 40,
                  color: item.isDir
                      ? const Color(0xFFDD8D2B)
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                ),
                const SizedBox(height: 6),
                Text(
                  item.name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: Theme.of(context)
                      .textTheme
                      .labelSmall
                      ?.copyWith(fontSize: 10),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  // -- Classified list view --------------------------------------------------
  Widget _buildClassifiedList() {
    return ListView.separated(
      itemCount: _classes.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (ctx, i) {
        final c = _classes[i];
        final selected = _selectedClassIdx == i;
        final cs = Theme.of(context).colorScheme;
        return ListTile(
          selected: selected,
          selectedTileColor: cs.primaryContainer.withOpacity(0.3),
          leading: CircleAvatar(
            backgroundColor: cs.primaryContainer,
            child: Icon(c.icon, color: cs.onPrimaryContainer, size: 20),
          ),
          title: Text(c.label),
          subtitle: Text(
            c.fileCount > 0
                ? '${c.fileCount} files · ${formatBytes(c.sizeBytes)}'
                : 'Not yet classified',
          ),
          onTap: () =>
              setState(() => _selectedClassIdx = selected ? null : i),
        );
      },
    );
  }

  // -- Classified icon/grid view ---------------------------------------------
  Widget _buildClassifiedGrid() {
    final cs = Theme.of(context).colorScheme;
    return GridView.builder(
      padding: const EdgeInsets.all(12),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 90,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: 0.75,
      ),
      itemCount: _classes.length,
      itemBuilder: (ctx, i) {
        final c = _classes[i];
        final selected = _selectedClassIdx == i;
        return InkWell(
          onTap: () =>
              setState(() => _selectedClassIdx = selected ? null : i),
          borderRadius: BorderRadius.circular(8),
          child: Container(
            decoration: selected
                ? BoxDecoration(
                    border: Border.all(color: cs.primary, width: 2),
                    borderRadius: BorderRadius.circular(8),
                  )
                : null,
            padding: const EdgeInsets.all(4),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(c.icon, size: 40, color: cs.primary),
                const SizedBox(height: 6),
                Text(
                  c.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
                if (c.fileCount > 0)
                  Text(
                    '${c.fileCount}',
                    style: Theme.of(context)
                        .textTheme
                        .labelSmall
                        ?.copyWith(
                          color: cs.onSurfaceVariant,
                          fontSize: 9,
                        ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  // -- Status bar ------------------------------------------------------------
  Widget _buildStatusBar(ColorScheme cs) {
    String text = '';
    if (_tab == AppTab.explorer) {
      final dirs = _dirItems.where((e) => e.isDir).length;
      final files = _dirItems.where((e) => !e.isDir).length;
      if (!_isLoadingDir) {
        text = '$dirs folder${dirs != 1 ? 's' : ''}, $files file${files != 1 ? 's' : ''}';
      }
    } else if (_selectedClassIdx != null) {
      final c = _classes[_selectedClassIdx!];
      text = '${c.label}: ${c.fileCount} files · ${formatBytes(c.sizeBytes)}';
    }
    return Container(
      height: 28,
      color: cs.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      alignment: Alignment.centerLeft,
      child: Text(
        text,
        style: Theme.of(context)
            .textTheme
            .labelSmall
            ?.copyWith(color: cs.onSurfaceVariant),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Tab pill widget
// ---------------------------------------------------------------------------
class _TabPill extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _TabPill({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? cs.primaryContainer : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon,
                size: 16,
                color: selected ? cs.onPrimaryContainer : cs.onSurfaceVariant),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color:
                    selected ? cs.onPrimaryContainer : cs.onSurfaceVariant,
                fontWeight:
                    selected ? FontWeight.w600 : FontWeight.normal,
                fontSize: 13,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Byte formatter
// ---------------------------------------------------------------------------
String formatBytes(int bytes) {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  double value = bytes.toDouble();
  int i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return '${value.toStringAsFixed(1)} ${units[i]}';
}
