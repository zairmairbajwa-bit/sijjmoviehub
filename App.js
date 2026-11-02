import React, { useState, useEffect, useCallback } from 'react';
import {
  StyleSheet,
  Text,
  View,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  Dimensions,
  SafeAreaView,
  StatusBar,
  TextInput,
  ScrollView,
  Image,
  Platform,
  Alert,
  BackHandler
} from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';

let FileSystem;
try {
  FileSystem = require('expo-file-system/legacy');
} catch (e) {
  FileSystem = require('expo-file-system');
}

const { width } = Dimensions.get('window');
const FIREBASE_BASE_URL = "https://sijjmoviehub-default-rtdb.firebaseio.com";
const RENDER_CLOUD_BACKEND = "https://sijjmoviehub.onrender.com/api/leech-and-stream?tmdb_id=";

function NativeVideoPlayer({ streamUrl, onClosePlayer }) {
  const [buffering, setBuffering] = useState(true);

  const player = useVideoPlayer(streamUrl, (p) => {
    try {
      p.loop = false;
      p.play();
    } catch (e) {}
  });

  useEffect(() => {
    setBuffering(true);
    let sub;
    try {
      sub = player.addListener('statusChange', (ev) => {
        const currentStatus = ev?.status || player.status;
        if (currentStatus === 'readyToPlay') {
          setBuffering(false);
          try {
            player.play();
          } catch (e) {}
        } else if (currentStatus === 'loading') {
          setBuffering(true);
        }
      });
    } catch (e) {}

    const timer = setTimeout(() => {
      setBuffering(false);
    }, 4500);

    return () => {
      clearTimeout(timer);
      if (sub && sub.remove) sub.remove();
    };
  }, [streamUrl, player]);

  return (
    <View style={styles.playerBox}>
      <VideoView
        style={styles.videoElement}
        player={player}
        allowsFullscreen
        allowsPictureInPicture
        nativeControls={true}
        contentFit="contain"
      />

      {buffering && (
        <View style={styles.spinnerOverlay} pointerEvents="none">
          <ActivityIndicator size="large" color="#E50914" />
          <Text style={styles.spinnerText}>Loading Telethon Stream...</Text>
        </View>
      )}

      <TouchableOpacity
        style={styles.topLeftBackButton}
        onPress={onClosePlayer}
        activeOpacity={0.8}
      >
        <Text style={styles.topLeftBackIcon}>⬅ Back</Text>
      </TouchableOpacity>
    </View>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorText: '' };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, errorText: error ? error.toString() : 'Unknown Error' };
  }
  render() {
    if (this.state.hasError) {
      return (
        <SafeAreaView style={styles.errorScreen}>
          <Text style={styles.errorTitle}>Application Exception Guard</Text>
          <Text style={styles.errorDesc}>{this.state.errorText}</Text>
          <TouchableOpacity
            style={styles.errorResetBtn}
            onPress={() => this.setState({ hasError: false })}
          >
            <Text style={styles.errorResetText}>Restart Application</Text>
          </TouchableOpacity>
        </SafeAreaView>
      );
    }
    return this.props.children;
  }
}

function MainApp() {
  const [movies, setMovies] = useState([]);
  const [filteredMovies, setFilteredMovies] = useState([]);
  const [loading, setLoading] = useState(true);

  const [selectedMovie, setSelectedMovie] = useState(null);
  const [resolvedStreamUrl, setResolvedStreamUrl] = useState(null);
  const [resolvingStream, setResolvingStream] = useState(false);
  const [activeTab, setActiveTab] = useState('Movies');
  const [searchQuery, setSearchQuery] = useState('');

  const [downloads, setDownloads] = useState([]);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadProgress, setDownloadProgress] = useState(0);

  useEffect(() => {
    fetchMetadataFromDatabase();
    syncExistingSandboxFiles();
  }, []);

  const handleClosePlayer = useCallback(() => {
    if (selectedMovie) {
      setSelectedMovie(null);
      setResolvedStreamUrl(null);
      return true;
    }
    if (activeTab !== 'Movies') {
      setActiveTab('Movies');
      return true;
    }
    return false;
  }, [selectedMovie, activeTab]);

  useEffect(() => {
    const backSubscription = BackHandler.addEventListener(
      'hardwareBackPress',
      handleClosePlayer
    );
    return () => backSubscription.remove();
  }, [handleClosePlayer]);

  const fetchMetadataFromDatabase = async () => {
    try {
      const resMovies = await fetch(`${FIREBASE_BASE_URL}/movies.json`);
      const dataMovies = await resMovies.json();
      let rawData = dataMovies;

      if (!rawData || typeof rawData !== 'object') {
        const resRoot = await fetch(`${FIREBASE_BASE_URL}/.json`);
        const dataRoot = await resRoot.json();
        rawData = dataRoot.movies || dataRoot;
      }

      if (rawData && typeof rawData === 'object') {
        const parsedList = [];
        const extractItems = (obj) => {
          Object.keys(obj).forEach((key) => {
            const item = obj[key];
            if (!item || typeof item !== 'object') return;
            if (item.title || item.tmdb_id || item.poster) {
              parsedList.push({
                id: String(item.tmdb_id || key),
                tmdb_id: String(item.tmdb_id || key),
                title: String(item.title || 'Untitled Movie'),
                overview: String(item.overview || ''),
                poster: String(item.poster || 'https://via.placeholder.com/300x450?text=No+Poster'),
                category: item.hindi_dubbed ? 'Trending Hollywood (Hindi Dubbed)' : 'Popular Updates'
              });
            } else {
              extractItems(item);
            }
          });
        };
        extractItems(rawData);
        setMovies(parsedList);
        setFilteredMovies(parsedList);
      }
    } catch (error) {
      console.log("Database fetch error:", error);
    } finally {
      setLoading(false);
    }
  };

  const syncExistingSandboxFiles = async () => {
    if (Platform.OS === 'web' || !FileSystem || !FileSystem.documentDirectory) return;
    try {
      const files = await FileSystem.readDirectoryAsync(FileSystem.documentDirectory);
      const hiddenFiles = files.filter((f) => f.startsWith('hidden_movie_') && f.endsWith('.mp4'));
      const restored = await Promise.all(
        hiddenFiles.map(async (filename) => {
          const fileUri = FileSystem.documentDirectory + filename;
          const info = await FileSystem.getInfoAsync(fileUri);
          if (!info.exists || info.size < 10000) return null;
          const movieId = filename.replace('hidden_movie_', '').replace('.mp4', '');
          return {
            id: movieId,
            title: `Offline Movie (${movieId})`,
            poster: 'https://via.placeholder.com/300x450/1f1f1f/E50914?text=Offline',
            uri: fileUri,
            sizeLabel: `${(info.size / (1024 * 1024)).toFixed(1)} MB`
          };
        })
      );
      setDownloads(restored.filter(Boolean));
    } catch (e) {}
  };

  const handleSearch = (text) => {
    setSearchQuery(text);
    if (!text || text.trim() === '') {
      setFilteredMovies(movies);
      return;
    }
    const q = text.toLowerCase();
    const localMatches = movies.filter(
      (m) =>
        (m.title && m.title.toLowerCase().includes(q)) ||
        (m.tmdb_id && String(m.tmdb_id).includes(q))
    );
    setFilteredMovies(localMatches);
  };

  const handleSelectMovie = async (movie) => {
    if (!movie) return;
    setSelectedMovie(movie);
    setResolvingStream(true);

    const movieId = movie.tmdb_id || movie.id;
    const sandboxFileUri = FileSystem.documentDirectory + 'hidden_movie_' + movieId + '.mp4';

    if (Platform.OS !== 'web' && FileSystem) {
      try {
        const info = await FileSystem.getInfoAsync(sandboxFileUri);
        if (info.exists && info.size > 10000) {
          setResolvedStreamUrl(sandboxFileUri);
          setResolvingStream(false);
          return;
        }
      } catch (e) {}
    }

    try {
      const res = await fetch(`${RENDER_CLOUD_BACKEND}${movieId}`);
      const data = await res.json();
      if (data && data.success && data.stream_url) {
        setResolvedStreamUrl(data.stream_url);
      } else {
        setResolvedStreamUrl(`https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4`);
      }
    } catch (err) {
      setResolvedStreamUrl(`https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4`);
    } finally {
      setResolvingStream(false);
    }
  };

  const handleDownloadMovie = async () => {
    if (!selectedMovie) return;
    if (Platform.OS === 'web' || !FileSystem || !FileSystem.documentDirectory) {
      Alert.alert("Notice", "Offline downloads only supported on Android devices.");
      return;
    }

    const movieId = selectedMovie.tmdb_id || selectedMovie.id;
    const fileUri = FileSystem.documentDirectory + 'hidden_movie_' + movieId + '.mp4';

    setDownloadingId(movieId);
    setDownloadProgress(0.01);

    try {
      const targetUrl = resolvedStreamUrl;
      const downloadResumable = FileSystem.createDownloadResumable(
        targetUrl,
        fileUri,
        {},
        (progressData) => {
          if (progressData && progressData.totalBytesExpectedToWrite > 0) {
            const ratio = progressData.totalBytesWritten / progressData.totalBytesExpectedToWrite;
            setDownloadProgress(Math.min(1, Math.max(0.01, ratio)));
          }
        }
      );

      const result = await downloadResumable.downloadAsync();
      setDownloadingId(null);

      if (result && result.uri) {
        setDownloads((prev) => [
          {
            id: movieId,
            title: selectedMovie.title,
            poster: selectedMovie.poster,
            uri: result.uri,
            sizeLabel: 'Cached'
          },
          ...prev.filter((d) => d.id !== movieId)
        ]);
        Alert.alert("Download Complete ✅", "Movie safely stored in private sandbox cache!");
        setResolvedStreamUrl(result.uri);
      }
    } catch (err) {
      setDownloadingId(null);
      Alert.alert("Download Error", "Failed to download stream.");
    }
  };

  const handleDeleteDownload = async (item) => {
    try {
      if (item.uri && FileSystem) {
        await FileSystem.deleteAsync(item.uri, { idempotent: true });
      }
    } catch (e) {}
    setDownloads((prev) => prev.filter((d) => d.id !== item.id));
  };

  if (loading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" color="#E50914" />
        <Text style={styles.loadingText}>Loading SijjMoviesHub Catalog...</Text>
      </View>
    );
  }

  const hindiDubbedList = filteredMovies.filter(m => m.category.includes('Hindi'));
  const popularList = filteredMovies.filter(m => !m.category.includes('Hindi'));

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#0f0f0f" />

      {selectedMovie ? (
        <View style={styles.playerScreenContainer}>
          {resolvingStream || !resolvedStreamUrl ? (
            <View style={styles.playerBox}>
              <ActivityIndicator size="large" color="#E50914" />
              <Text style={styles.spinnerText}>Leeching from Telegram Channel...</Text>
              <TouchableOpacity
                style={styles.topLeftBackButton}
                onPress={() => {
                  setSelectedMovie(null);
                  setResolvedStreamUrl(null);
                }}
              >
                <Text style={styles.topLeftBackIcon}>⬅ Back</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <NativeVideoPlayer
              key={resolvedStreamUrl}
              streamUrl={resolvedStreamUrl}
              onClosePlayer={() => {
                setSelectedMovie(null);
                setResolvedStreamUrl(null);
              }}
            />
          )}

          <ScrollView style={styles.detailsScrollBox} contentContainerStyle={styles.detailsScrollContent}>
            <Text style={styles.detailMovieTitle}>{selectedMovie.title}</Text>

            <View style={styles.badgeRow}>
              <View style={styles.categoryBadge}>
                <Text style={styles.categoryBadgeText}>{selectedMovie.category}</Text>
              </View>
            </View>

            <Text style={styles.overviewText} numberOfLines={4}>
              {selectedMovie.overview || "No overview available for this title."}
            </Text>

            {downloadingId === (selectedMovie.tmdb_id || selectedMovie.id) ? (
              <View style={styles.downloadingIndicatorBox}>
                <ActivityIndicator size="small" color="#E50914" />
                <Text style={styles.downloadingText}>
                  Downloading... {Math.round(downloadProgress * 100)}%
                </Text>
                <View style={styles.progressBarTrack}>
                  <View style={[styles.progressBarFill, { width: `${Math.round(downloadProgress * 100)}%` }]} />
                </View>
              </View>
            ) : (
              <TouchableOpacity
                style={styles.primaryDownloadBtn}
                onPress={handleDownloadMovie}
                activeOpacity={0.85}
              >
                <Text style={styles.primaryDownloadBtnText}>📥 Download & Keep in App</Text>
              </TouchableOpacity>
            )}
          </ScrollView>
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          <View style={styles.header}>
            <Text style={styles.headerTitle}>
              Sijj<Text style={{ color: '#E50914' }}>MoviesHub</Text>
            </Text>
          </View>

          {activeTab === 'Movies' ? (
            <ScrollView contentContainerStyle={{ paddingBottom: 90 }}>
              <View style={styles.searchContainer}>
                <TextInput
                  style={styles.searchInput}
                  placeholder="Search movies..."
                  placeholderTextColor="#888"
                  value={searchQuery}
                  onChangeText={handleSearch}
                />
              </View>

              <Text style={styles.sectionTitle}>🇮🇳 Trending Hollywood (Hindi Dubbed)</Text>
              <FlatList
                data={hindiDubbedList.length > 0 ? hindiDubbedList : filteredMovies}
                keyExtractor={(item, idx) => 'hindi_' + (item.id || idx)}
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ paddingHorizontal: 10 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={styles.horizontalMovieCard}
                    onPress={() => handleSelectMovie(item)}
                  >
                    <Image source={{ uri: item.poster }} style={styles.horizontalPoster} />
                    <Text style={styles.horizontalCardTitle} numberOfLines={1}>{item.title}</Text>
                  </TouchableOpacity>
                )}
              />

              <Text style={styles.sectionTitle}>🔥 Popular Updates</Text>
              <FlatList
                data={popularList.length > 0 ? popularList : filteredMovies}
                keyExtractor={(item, idx) => 'pop_' + (item.id || idx)}
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ paddingHorizontal: 10 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={styles.horizontalMovieCard}
                    onPress={() => handleSelectMovie(item)}
                  >
                    <Image source={{ uri: item.poster }} style={styles.horizontalPoster} />
                    <Text style={styles.horizontalCardTitle} numberOfLines={1}>{item.title}</Text>
                  </TouchableOpacity>
                )}
              />
            </ScrollView>
          ) : (
            <View style={styles.downloadsSectionContainer}>
              <Text style={styles.sectionTitle}>📥 Offline Sandbox Cache</Text>
              {downloads.length === 0 ? (
                <View style={styles.emptyDownloadsBox}>
                  <Text style={styles.emptyDownloadsIcon}>📂</Text>
                  <Text style={styles.emptyDownloadsTitle}>No Cached Movies Yet</Text>
                </View>
              ) : (
                <FlatList
                  data={downloads}
                  keyExtractor={(item) => item.id}
                  contentContainerStyle={{ padding: 12, paddingBottom: 90 }}
                  renderItem={({ item }) => (
                    <View style={styles.downloadItemCard}>
                      <Image source={{ uri: item.poster }} style={styles.downloadThumb} />
                      <View style={styles.downloadInfoCol}>
                        <Text style={styles.downloadItemTitle} numberOfLines={1}>
                          {item.title}
                        </Text>
                        <View style={styles.downloadActionsRow}>
                          <TouchableOpacity
                            style={styles.playOfflineBtn}
                            onPress={() => {
                              setSelectedMovie({
                                id: item.id,
                                title: item.title,
                                category: 'Offline Sandbox',
                                poster: item.poster
                              });
                              setResolvedStreamUrl(item.uri);
                            }}
                          >
                            <Text style={styles.playOfflineBtnText}>▶ Watch Offline</Text>
                          </TouchableOpacity>

                          <TouchableOpacity
                            style={styles.deleteDownloadBtn}
                            onPress={() => handleDeleteDownload(item)}
                          >
                            <Text style={styles.deleteDownloadBtnText}>🗑 Remove</Text>
                          </TouchableOpacity>
                        </View>
                      </View>
                    </View>
                  )}
                />
              )}
            </View>
          )}

          <View style={styles.bottomTabBar}>
            <TouchableOpacity
              style={[styles.tabButton, activeTab === 'Movies' && styles.tabButtonActive]}
              onPress={() => setActiveTab('Movies')}
            >
              <Text style={[styles.tabButtonText, activeTab === 'Movies' && styles.tabButtonTextActive]}>
                🎬 Movies List
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.tabButton, activeTab === 'Downloads' && styles.tabButtonActive]}
              onPress={() => setActiveTab('Downloads')}
            >
              <Text style={[styles.tabButtonText, activeTab === 'Downloads' && styles.tabButtonTextActive]}>
                📥 Offline Cache {downloads.length > 0 ? `(${downloads.length})` : ''}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <MainApp />
    </ErrorBoundary>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f0f0f' },
  loadingScreen: { flex: 1, backgroundColor: '#0f0f0f', justifyContent: 'center', alignItems: 'center' },
  loadingText: { color: '#fff', marginTop: 12, fontSize: 16, fontWeight: '600' },
  errorScreen: { flex: 1, backgroundColor: '#0f0f0f', justifyContent: 'center', padding: 24 },
  errorTitle: { color: '#E50914', fontSize: 22, fontWeight: 'bold', marginBottom: 8 },
  errorDesc: { color: '#ccc', fontSize: 14, marginBottom: 20 },
  errorResetBtn: { backgroundColor: '#E50914', padding: 14, borderRadius: 8, alignItems: 'center' },
  errorResetText: { color: '#fff', fontWeight: 'bold', fontSize: 16 },
  header: {
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: '#161616',
    borderBottomWidth: 1,
    borderBottomColor: '#262626',
    alignItems: 'center'
  },
  headerTitle: { fontSize: 22, fontWeight: '800', color: '#fff', letterSpacing: 0.5 },
  searchContainer: { padding: 12, backgroundColor: '#141414' },
  searchInput: {
    backgroundColor: '#242424',
    color: '#fff',
    paddingHorizontal: 16,
    paddingVertical: 11,
    borderRadius: 10,
    fontSize: 14,
    borderWidth: 1,
    borderColor: '#333'
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
    marginHorizontal: 14,
    marginTop: 16,
    marginBottom: 10
  },
  horizontalMovieCard: {
    width: 130,
    marginRight: 10,
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    overflow: 'hidden'
  },
  horizontalPoster: { width: 130, height: 180, resizeMode: 'cover', backgroundColor: '#262626' },
  horizontalCardTitle: {
    color: '#eee',
    fontSize: 12,
    fontWeight: '600',
    padding: 6,
    textAlign: 'center'
  },
  playerScreenContainer: { flex: 1, backgroundColor: '#0f0f0f' },
  playerBox: {
    width: width,
    height: 260,
    backgroundColor: '#000',
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
    overflow: 'hidden'
  },
  videoElement: { width: width, height: 260, backgroundColor: '#000' },
  spinnerOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 99
  },
  spinnerText: { color: '#fff', marginTop: 10, fontSize: 13, fontWeight: '600' },
  topLeftBackButton: {
    position: 'absolute',
    top: 40,
    left: 20,
    backgroundColor: 'rgba(20, 20, 20, 0.85)',
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.25)',
    zIndex: 100
  },
  topLeftBackIcon: { color: '#fff', fontSize: 14, fontWeight: 'bold' },
  detailsScrollBox: { flex: 1, backgroundColor: '#0f0f0f' },
  detailsScrollContent: { padding: 18, paddingBottom: 50 },
  detailMovieTitle: {
    color: '#fff',
    fontSize: 22,
    fontWeight: 'bold',
    lineHeight: 28,
    marginBottom: 10
  },
  badgeRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 },
  categoryBadge: {
    backgroundColor: 'rgba(229, 9, 20, 0.18)',
    borderWidth: 1,
    borderColor: '#E50914',
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 6,
    marginRight: 10
  },
  categoryBadgeText: { color: '#E50914', fontSize: 12, fontWeight: '700' },
  overviewText: { color: '#aaa', fontSize: 14, lineHeight: 20, marginBottom: 18 },
  primaryDownloadBtn: {
    backgroundColor: '#E50914',
    paddingVertical: 15,
    borderRadius: 10,
    alignItems: 'center',
    marginBottom: 18
  },
  primaryDownloadBtnText: { color: '#fff', fontSize: 16, fontWeight: 'bold' },
  downloadingIndicatorBox: {
    backgroundColor: '#1f1f1f',
    padding: 14,
    borderRadius: 10,
    alignItems: 'center',
    marginBottom: 18,
    borderWidth: 1,
    borderColor: '#333'
  },
  downloadingText: { color: '#fff', fontSize: 14, fontWeight: '600', marginVertical: 6 },
  progressBarTrack: {
    width: '100%',
    height: 6,
    backgroundColor: '#333',
    borderRadius: 3,
    overflow: 'hidden',
    marginTop: 6
  },
  progressBarFill: { height: '100%', backgroundColor: '#E50914' },
  downloadsSectionContainer: { flex: 1 },
  emptyDownloadsBox: { flex: 1, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 32 },
  emptyDownloadsIcon: { fontSize: 48, marginBottom: 12 },
  emptyDownloadsTitle: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  downloadItemCard: {
    flexDirection: 'row',
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    padding: 10,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#2a2a2a'
  },
  downloadThumb: { width: 70, height: 100, borderRadius: 6, backgroundColor: '#2b2b2b' },
  downloadInfoCol: { flex: 1, marginLeft: 12, justifyContent: 'space-around' },
  downloadItemTitle: { color: '#fff', fontSize: 15, fontWeight: 'bold' },
  downloadActionsRow: { flexDirection: 'row', alignItems: 'center' },
  playOfflineBtn: {
    backgroundColor: '#E50914',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    marginRight: 10
  },
  playOfflineBtnText: { color: '#fff', fontSize: 12, fontWeight: 'bold' },
  deleteDownloadBtn: {
    backgroundColor: '#2b2b2b',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6
  },
  deleteDownloadBtnText: { color: '#ccc', fontSize: 12 },
  bottomTabBar: {
    flexDirection: 'row',
    height: 62,
    backgroundColor: '#161616',
    borderTopWidth: 1,
    borderTopColor: '#2a2a2a',
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    paddingHorizontal: 12,
    alignItems: 'center'
  },
  tabButton: {
    flex: 1,
    paddingVertical: 11,
    marginHorizontal: 6,
    borderRadius: 8,
    alignItems: 'center',
    backgroundColor: '#222'
  },
  tabButtonActive: { backgroundColor: '#E50914' },
  tabButtonText: { color: '#aaa', fontSize: 14, fontWeight: '700' },
  tabButtonTextActive: { color: '#fff' }
});