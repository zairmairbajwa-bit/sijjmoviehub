from flask import Flask, jsonify, request

app = Flask(__name__)

# Yahan aap apni marzi ki Hindi dubbed movies aur unke links khud add kar sakte hain!
movies_database = [
    {
        "id": 1,
        "title": "Avatar: The Way of Water (Hindi Dubbed)",
        "stream_url": "https://vidlink.pro/movie/76600?audio=hi",
        "poster": "https://image.tmdb.org/t/p/w500/t6HIqrRAclMCA60NsSmeqe9RmNV.jpg"
    },
    {
        "id": 2,
        "title": "Avengers: Endgame (Hindi Dubbed)",
        "stream_url": "https://vidlink.pro/movie/299534?audio=hi",
        "poster": "https://image.tmdb.org/t/p/w500/ulzhLuHPkJWO7HACXkUnzTZD08v.jpg"
    }
]

# API Endpoint jahan se mobile app data uthayegi
@app.route('/movies', methods=['GET'])
def get_movies():
    return jsonify(movies_database)

# Nayi movie add karne ka route (Agar future mein bot ya admin panel banana ho)
@app.route('/add-movie', methods=['POST'])
def add_movie():
    new_data = request.json
    movies_database.append(new_data)
    return jsonify({"status": "Success", "message": "Movie added successfully!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)