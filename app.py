from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, render_template, session, url_for, redirect
from flask_sqlalchemy import SQLAlchemy
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = 'hueta'  # Лучше вынести в config позже

# Подключение к PostgreSQL на WSL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://cinema_user:cinema_pass@172.27.94.52/online_cinema'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'movie'  # Папка для видео
app.config['POSTER_FOLDER'] = 'posters'

db = SQLAlchemy(app)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.accept_mimetypes.accept_json:
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('movie_id', db.Integer, db.ForeignKey('movie.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    favorite_movies = db.relationship('Movie', secondary=favorites, backref='favorited_by')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Модель фильма
class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer)
    country = db.Column(db.String(100))
    genre = db.Column(db.String(100))
    slogan = db.Column(db.String(255))
    director = db.Column(db.String(100))
    writer = db.Column(db.String(100))
    video_filename = db.Column(db.String(500))
    poster_filename = db.Column(db.String(500))
    views = db.Column(db.Integer, default=0)

    comments = db.relationship('Comment', backref='movie', lazy='dynamic')

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer)  # от 1 до 5
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')

# Создание таблиц
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    genre = request.args.get('genre', '').strip()
    country = request.args.get('country', '').strip()
    year = request.args.get('year', '').strip()

    movies = Movie.query

    if query:
        movies = movies.filter(Movie.title.ilike(f"%{query}%"))
    if genre:
        movies = movies.filter(Movie.genre.ilike(f"%{genre}%"))
    if country:
        movies = movies.filter(Movie.country.ilike(f"%{country}%"))
    if year and year.isdigit():
        movies = movies.filter(Movie.year == int(year))

    movies = movies.all()

    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])

    movie_ratings = {}
    for movie in movies:
        ratings = [c.rating for c in movie.comments if c.rating]
        if ratings:
            avg = round(sum(ratings) / len(ratings), 1)
            movie_ratings[movie.id] = avg

    return render_template(
        'index.html',
        movies=movies,
        user=user,
        movie_ratings=movie_ratings,
        query=query,
        genre=genre,
        country=country,
        year=year
    )


# Роут: Загрузка видео
@app.route('/upload', methods=['POST'])
def upload_video():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = file.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    return jsonify({"message": "Video uploaded successfully", "video_url": f"/videos/{filename}"}), 201

# Роут: Раздача видеофайлов
@app.route('/videos/<filename>')
def get_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Роут: HTML-страница с плеером
@app.route('/watch/<filename>')
def watch_video(filename):
    video_url = f"/videos/{filename}"
    return render_template("watch.html", video_url=video_url)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Имя пользователя уже занято")

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        return redirect(url_for('index'))

    return render_template('register.html')



# Вход пользователя
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form
        username = data.get('username')
        password = data.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Неверный логин или пароль")

    return render_template('login.html')




@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/upload_form')
@login_required
def upload_form():
    return render_template('upload.html')

@app.route('/add_movie', methods=['GET', 'POST'])
@login_required
def add_movie():
    user = User.query.get(session['user_id'])
    if not user.is_admin:
        return "Доступ запрещён", 403
    if request.method == 'POST':
        data = request.form
        video_file = request.files.get('file')
        poster_file = request.files.get('poster')

        if not video_file or not video_file.filename.endswith('.mp4'):
            return "Файл не выбран или не .mp4", 400

        video_filename = video_file.filename
        video_file.save(os.path.join(app.config['UPLOAD_FOLDER'], video_filename))

        poster_filename = None
        if poster_file and poster_file.filename != '':
            poster_filename = poster_file.filename
            poster_file.save(os.path.join(app.config['POSTER_FOLDER'], poster_filename))

        movie = Movie(
            title=data.get('title'),
            year=int(data.get('year')) if data.get('year') else None,
            country=data.get('country'),
            genre=data.get('genre'),
            slogan=data.get('slogan'),
            director=data.get('director'),
            writer=data.get('writer'),
            video_filename=video_filename,
            poster_filename=poster_filename
        )
        db.session.add(movie)
        db.session.commit()

        return redirect(url_for('index'))

    return render_template('add_movie.html')

@app.route('/posters/<filename>')
def get_poster(filename):
    return send_from_directory(app.config['POSTER_FOLDER'], filename)


@app.route('/movie/<int:movie_id>', methods=['GET', 'POST'])
def movie_details(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    if request.method == 'POST':
        if 'user_id' not in session:
            return redirect(url_for('login'))

        text = request.form.get('text')
        rating = int(request.form.get('rating') or 0)
        if text:
            comment = Comment(
                movie_id=movie.id,
                user_id=session['user_id'],
                text=text,
                rating=rating if 1 <= rating <= 5 else None
            )
            db.session.add(comment)
            db.session.commit()
        return redirect(url_for('movie_details', movie_id=movie.id))

    movie.views += 1
    db.session.commit()
    comments = Comment.query.filter_by(movie_id=movie.id).order_by(Comment.created_at.desc()).all()

    avg_rating = (
        db.session.query(db.func.avg(Comment.rating))
        .filter(Comment.movie_id == movie.id, Comment.rating.isnot(None))
        .scalar()
    )
    avg_rating = round(avg_rating, 1) if avg_rating else None

    return render_template(
        "movie_details.html",
        movie=movie,
        comments=comments,
        avg_rating=avg_rating
    )

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    comments = Comment.query.filter_by(user_id=user.id).order_by(Comment.created_at.desc()).all()
    favorites = user.favorite_movies
    return render_template("profile.html", user=user, comments=comments, favorites=favorites)

@app.route('/favorite/<int:movie_id>')
@login_required
def toggle_favorite(movie_id):
    user = User.query.get(session['user_id'])
    movie = Movie.query.get_or_404(movie_id)

    if movie in user.favorite_movies:
        user.favorite_movies.remove(movie)
    else:
        user.favorite_movies.append(movie)

    db.session.commit()
    return redirect(request.referrer or url_for('index'))


# Запуск сервера Flask
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5002)
