import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  FlatList,
  Image,
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  Dimensions,
} from 'react-native';
import { WebView } from 'react-native-webview';

const { width } = Dimensions.get('window');
const TMDB_API_KEY = '7b6a89d3dc55b3a81aa892a88c0da6b9';

export default function App() {
  const [activeTab, setActiveTab] = useState('home'); // 'home', 'search', 'details'
  const [trendingMovies, setTrendingMovies] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [loading, setLoading] = useState(false);

  // Bot Server se aane wali custom Hindi dubbed movies ki list
  const [botMovies, setBotMovies] = useState([]);

  // Season & Episode States for TV Series
  const [season, setSeason] = useState('1');
  const [episode, setEpisode] = useState('1');

  useEffect(() => {
    fetchTrending();
    fetchBotServerMovies();
  }, []);

  // 1. Fetch Global Trending Hollywood & Series from TMDB
  const fetchTrending = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `https://api.themoviedb.org/3/trending/all/day?api_key=${TMDB_API_KEY}&language=en-US`
      );
      const data = await response.json();
      setTrendingMovies(data.results || []);
    } catch (error) {
      console.log('Error fetching trending:', error);
    }
    setLoading(false);
  };

  // 2. Fetch Movies from Your Local Flask Bot Server
  const fetchBotServerMovies = async () => {
    try {
      const response = await fetch('http://192.168.10.6:5000/movies');
      const data = await response.json();
      setBotMovies(data || []);
    } catch (error) {
      console.log('Error connecting to bot server:', error);
    }
  };

  // Real-time Search
  const handleSearch = async (text) => {
    setSearchQuery(text);
    if (!text.trim()) {
      setSearchResults([]);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(
        `https://api.themoviedb.org/3/search/multi?api_key=${TMDB_API_KEY}&query=${encodeURIComponent(
          text
        )}&language=en-US`
      );
      const data = await response.json();
      const filteredResults = (data.results || []).filter(
        (item) => item.media_type === 'movie' || item.media_type === 'tv'
      );
      setSearchResults(filteredResults);
    } catch (error) {
      console.log('Error searching:', error);
    }
    setLoading(false);
  };

  // Check if bot server has a custom link for this movie, otherwise use default VidLink with Hindi forced
  const getStreamUrl = () => {
    if (!selectedItem) return '';

    const title = (selectedItem.title || selectedItem.name || '').toLowerCase();
    
    // Check if bot database has this movie title
    const matchedBotMovie = botMovies.find(
      (m) => m.title.toLowerCase().includes(title) || title.includes(m.title.toLowerCase())
    );

    if (matchedBotMovie && matchedBotMovie.stream_url) {
      console.log("Playing from Bot Server:", matchedBotMovie.title);
      return matchedBotMovie.stream_url;
    }

    // Fallback to VidLink with forced Hindi audio/subs
    const isTv = selectedItem.media_type === 'tv' || selectedItem.first_air_date;
    const id = selectedItem.id;
    const s = season || '1';
    const e = episode || '1';

    return isTv
      ? `https://vidlink.pro/tv/${id}/${s}/${e}?audio=hi&sub=hi`
      : `https://vidlink.pro/movie/${id}?audio=hi&sub=hi`;
  };

  const renderCard = ({ item }) => {
    const title = item.title || item.name;
    const poster = item.poster_path
      ? `https://image.tmdb.org/t/p/w500${item.poster_path}`
      : 'https://via.placeholder.com/500x750?text=No+Poster';
    const isTv = item.media_type === 'tv' || item.first_air_date;

    return (
      <TouchableOpacity
        style={styles.card}
        onPress={() => {
          setSelectedItem(item);
          setSeason('1');
          setEpisode('1');
          setActiveTab('details');
        }}
      >
        <Image source={{ uri: poster }} style={styles.poster} />
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{isTv ? 'HD SERIES' : 'HINDI DUB'}</Text>
        </View>
        <Text style={styles.cardTitle} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.cardSub}>
          ⭐ {item.vote_average ? item.vote_average.toFixed(1) : '8.0'} | {isTv ? 'Series' : 'Movie'}
        </Text>
      </TouchableOpacity>
    );
  };

  const isSelectedTv =
    selectedItem && (selectedItem.media_type === 'tv' || selectedItem.first_air_date);

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.logo}>
          Sijj<Text style={{ color: '#e50914' }}>MovieHub</Text>
        </Text>
        <View style={styles.navButtons}>
          <TouchableOpacity
            style={[styles.navBtn, activeTab === 'home' && styles.activeNavBtn]}
            onPress={() => {
              setActiveTab('home');
              setSelectedItem(null);
            }}
          >
            <Text style={styles.navText}>Home</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.navBtn, activeTab === 'search' && styles.activeNavBtn]}
            onPress={() => setActiveTab('search')}
          >
            <Text style={styles.navText}>Search</Text>
          </TouchableOpacity>
        </View>
      </View>

      {loading && (
        <View style={styles.loaderContainer}>
          <ActivityIndicator size="large" color="#e50914" />
        </View>
      )}

      {/* HOME TAB */}
      {activeTab === 'home' && !loading && (
        <View style={styles.content}>
          <Text style={styles.sectionTitle}>🔥 Trending Hollywood & Series</Text>
          <FlatList
            data={trendingMovies}
            renderItem={renderCard}
            keyExtractor={(item) => item.id.toString()}
            numColumns={2}
            columnWrapperStyle={styles.columnWrapper}
            showsVerticalScrollIndicator={false}
          />
        </View>
      )}

      {/* SEARCH TAB */}
      {activeTab === 'search' && (
        <View style={styles.content}>
          <View style={styles.searchBoxContainer}>
            <TextInput
              style={styles.input}
              placeholder="Search any Hollywood movie or series..."
              placeholderTextColor="#888"
              value={searchQuery}
              onChangeText={handleSearch}
            />
          </View>

          <FlatList
            data={searchResults}
            renderItem={renderCard}
            keyExtractor={(item) => item.id.toString()}
            numColumns={2}
            columnWrapperStyle={styles.columnWrapper}
            showsVerticalScrollIndicator={false}
          />
        </View>
      )}

      {/* DETAILS & PLAYER TAB */}
      {activeTab === 'details' && selectedItem && (
        <ScrollView style={styles.detailsContainer} showsVerticalScrollIndicator={false}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={() => setActiveTab('home')}
          >
            <Text style={styles.backButtonText}>❌ Back to Home</Text>
          </TouchableOpacity>

          <Text style={styles.detailTitle}>{selectedItem.title || selectedItem.name}</Text>

          {isSelectedTv && (
            <View style={styles.epRow}>
              <View style={styles.epInputBox}>
                <Text style={styles.epLabel}>Season:</Text>
                <TextInput
                  style={styles.epInput}
                  keyboardType="numeric"
                  value={season}
                  onChangeText={setSeason}
                />
              </View>
              <View style={styles.epInputBox}>
                <Text style={styles.epLabel}>Episode:</Text>
                <TextInput
                  style={styles.epInput}
                  keyboardType="numeric"
                  value={episode}
                  onChangeText={setEpisode}
                />
              </View>
            </View>
          )}

          <Text style={styles.audioHint}>
            💡 Note: Bot server se custom Hindi link check kiya ja raha hai, warna VidLink forced Hindi audio use hoga.
          </Text>

          <View style={styles.playerWrapper}>
            <WebView
              key={`${season}-${episode}`}
              source={{ uri: getStreamUrl() }}
              style={styles.webview}
              allowsFullscreenVideo={true}
              javaScriptEnabled={true}
              domStorageEnabled={true}
              setSupportMultipleWindows={false}
              onShouldStartLoadWithRequest={(request) => {
                const url = request.url;
                if (
                  url.includes('vidlink') ||
                  url.includes('vidsrc') ||
                  url.includes('cloudflare') ||
                  url.includes('google')
                ) {
                  return true;
                }
                return false;
              }}
              originWhitelist={['*']}
              mixedContentMode="always"
              userAgent="Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
            />
          </View>

          <Text style={styles.detailOverview}>
            {selectedItem.overview || 'No description available.'}
          </Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#222',
    marginTop: 24,
  },
  logo: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
  },
  navButtons: {
    flexDirection: 'row',
  },
  navBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginLeft: 6,
    borderRadius: 4,
    backgroundColor: '#222',
  },
  activeNavBtn: {
    backgroundColor: '#e50914',
  },
  navText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 12,
  },
  content: {
    flex: 1,
    padding: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 12,
  },
  columnWrapper: {
    justifyContent: 'space-between',
  },
  card: {
    width: width / 2 - 18,
    backgroundColor: '#1e1e1e',
    borderRadius: 8,
    marginBottom: 16,
    overflow: 'hidden',
  },
  poster: {
    width: '100%',
    height: 220,
    resizeMode: 'cover',
  },
  badge: {
    position: 'absolute',
    top: 8,
    right: 8,
    backgroundColor: 'rgba(229, 9, 20, 0.9)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  badgeText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: 'bold',
  },
  cardTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
    paddingHorizontal: 8,
    marginTop: 6,
  },
  cardSub: {
    color: '#aaa',
    fontSize: 12,
    paddingHorizontal: 8,
    marginBottom: 8,
  },
  searchBoxContainer: {
    marginBottom: 16,
  },
  input: {
    backgroundColor: '#1e1e1e',
    color: '#fff',
    paddingHorizontal: 12,
    height: 44,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#333',
  },
  loaderContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  detailsContainer: {
    flex: 1,
    padding: 16,
  },
  backButton: {
    backgroundColor: '#222',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    alignSelf: 'flex-start',
    marginBottom: 12,
  },
  backButtonText: {
    color: '#e50914',
    fontWeight: 'bold',
  },
  detailTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 10,
  },
  audioHint: {
    color: '#bbb',
    fontSize: 12,
    marginBottom: 10,
    backgroundColor: '#1e1e1e',
    padding: 8,
    borderRadius: 6,
  },
  epRow: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  epInputBox: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 20,
  },
  epLabel: {
    color: '#fff',
    marginRight: 8,
    fontWeight: 'bold',
  },
  epInput: {
    backgroundColor: '#222',
    color: '#fff',
    width: 50,
    height: 36,
    textAlign: 'center',
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#444',
  },
  playerWrapper: {
    width: '100%',
    height: 260,
    backgroundColor: '#000',
    borderRadius: 8,
    overflow: 'hidden',
    marginBottom: 16,
  },
  webview: {
    flex: 1,
  },
  detailOverview: {
    color: '#aaa',
    fontSize: 14,
    marginBottom: 40,
    lineHeight: 20,
  },
});