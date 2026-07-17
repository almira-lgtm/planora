import os
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g
import bcrypt

app = Flask(__name__)
app.secret_key = 'planora_secret_key_anda'

# Konfigurasi SQLite
DATABASE = os.path.join(app.root_path, 'planora.db')


def get_db():
    """Ambil koneksi SQLite untuk request saat ini (reuse via flask.g)."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Buat tabel jika file database belum ada / tabel belum ada."""
    db = get_db()
    schema_path = os.path.join(app.root_path, 'database.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        db.executescript(f.read())
    db.commit()


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


def is_logged_in():
    return 'user_id' in session


def update_not_completed_status(user_id):
    today_str = datetime.now().strftime('%Y-%m-%d')
    db = get_db()
    db.execute("""
        UPDATE contents
        SET status = 'Not Completed'
        WHERE user_id = ? AND publish_date < ? AND status != 'Done'
    """, (user_id, today_str))
    db.commit()


@app.route('/')
def landing():
    if is_logged_in(): return redirect(url_for('dashboard'))
    return render_template('landing.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash("Password tidak cocok!", "danger")
            return render_template('signup.html')

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO users(username, email, password) VALUES (?, ?, ?)",
                (username, email, hashed_pw)
            )
            db.commit()
            user_id = cur.lastrowid

            session['user_id'] = user_id
            session['username'] = username
            session['email'] = email
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash("Username atau Email sudah terdaftar!", "danger")
            return render_template('signup.html')

    return render_template('signup.html')


@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        user = row_to_dict(db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone())

        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user['email']
            return redirect(url_for('dashboard'))
        else:
            flash("Login Gagal! Periksa kembali username dan password.", "danger")
            return render_template('signin.html')

    return render_template('signin.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))


@app.route('/dashboard')
def dashboard():
    if not is_logged_in(): return redirect(url_for('signin'))

    update_not_completed_status(session['user_id'])

    db = get_db()
    stats_raw = rows_to_list(db.execute(
        "SELECT status, COUNT(*) as total FROM contents WHERE user_id = ? GROUP BY status",
        (session['user_id'],)
    ).fetchall())

    stats = {'Idea': 0, 'In Progress': 0, 'Done': 0, 'Not Completed': 0}
    for s in stats_raw:
        if s['status'] in stats:
            stats[s['status']] = s['total']

    return render_template('index.html', stats=stats)


@app.route('/my-content')
def my_content():
    if not is_logged_in(): return redirect(url_for('signin'))
    return render_template('my_content.html')


@app.route('/api/contents')
def get_contents():
    if not is_logged_in(): return jsonify({'error': 'Unauthorized'}), 401

    date_filter = request.args.get('date')
    status_filter = request.args.get('status')
    search_query = request.args.get('search', '')

    db = get_db()
    query = "SELECT * FROM contents WHERE user_id = ?"
    params = [session['user_id']]

    if date_filter:
        query += " AND publish_date = ?"
        params.append(date_filter)
    elif status_filter and status_filter != 'All':
        current_month = datetime.now().strftime('%Y-%m')
        query += " AND status = ? AND strftime('%Y-%m', publish_date) = ?"
        params.extend([status_filter, current_month])

    if search_query:
        query += " AND title LIKE ?"
        params.append(f"%{search_query}%")

    data = rows_to_list(db.execute(query, params).fetchall())

    # publish_date sudah tersimpan sebagai teks 'YYYY-MM-DD' di SQLite,
    # jadi tidak perlu konversi tambahan seperti di MySQL.

    return jsonify(data)


@app.route('/api/content/update-status', methods=['POST'])
def update_status():
    if not is_logged_in(): return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    content_id = data.get('id')
    new_status = data.get('status')

    db = get_db()
    db.execute(
        "UPDATE contents SET status = ? WHERE id = ? AND user_id = ?",
        (new_status, content_id, session['user_id'])
    )
    db.commit()

    return jsonify({'success': True})


# API GRAFIK: label grafik (Hari & Bulan) otomatis ke Bahasa Inggris jika session['lang'] == 'en'
@app.route('/api/chart-data')
def get_chart_data():
    if not is_logged_in(): return jsonify({'error': 'Unauthorized'}), 401

    period = request.args.get('period', 'weekly')
    user_id = session['user_id']
    is_english = (session.get('lang') == 'en')

    db = get_db()

    if period == 'weekly':
        dates_param = request.args.get('dates', '')
        weekly_dates = dates_param.split(',') if dates_param else []

        values = [0] * 7
        if weekly_dates:
            placeholders = ','.join(['?'] * len(weekly_dates))
            query = f"""
                SELECT publish_date, COUNT(*) as total
                FROM contents
                WHERE user_id = ? AND status = 'Done' AND publish_date IN ({placeholders})
                GROUP BY publish_date
            """
            results = rows_to_list(db.execute(query, [user_id] + weekly_dates).fetchall())

            for row in results:
                date_str = row['publish_date']
                if date_str in weekly_dates:
                    idx = weekly_dates.index(date_str)
                    values[idx] = row['total']

        return jsonify({'values': values})

    elif period == 'monthly':
        current_month = datetime.now().strftime('%Y-%m')
        results = rows_to_list(db.execute("""
            SELECT CAST(strftime('%d', publish_date) AS INTEGER) as hari_ke, COUNT(*) as total
            FROM contents
            WHERE user_id = ? AND status = 'Done' AND strftime('%Y-%m', publish_date) = ?
            GROUP BY hari_ke
        """, (user_id, current_month)).fetchall())

        labels = [str(i) for i in range(1, 32)]
        values = [0] * 31
        for row in results:
            hari_idx = int(row['hari_ke']) - 1
            if 0 <= hari_idx < 31:
                values[hari_idx] = row['total']

        return jsonify({'labels': labels, 'values': values})

    elif period == 'yearly':
        current_year = datetime.now().strftime('%Y')
        results = rows_to_list(db.execute("""
            SELECT CAST(strftime('%m', publish_date) AS INTEGER) as bulan_ke, COUNT(*) as total
            FROM contents
            WHERE user_id = ? AND status = 'Done' AND strftime('%Y', publish_date) = ?
            GROUP BY bulan_ke
        """, (user_id, current_year)).fetchall())

        if is_english:
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        else:
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

        values = [0] * 12
        for row in results:
            idx = int(row['bulan_ke']) - 1
            if 0 <= idx < 12:
                values[idx] = row['total']

        return jsonify({'labels': labels, 'values': values})


@app.route('/content/new', methods=['GET', 'POST'])
def new_content():
    if not is_logged_in(): return redirect(url_for('signin'))
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        category = request.form['category']
        status = request.form['status']
        publish_date = request.form['publish_date']

        db = get_db()
        db.execute(
            "INSERT INTO contents (user_id, title, description, category, status, publish_date) VALUES (?, ?, ?, ?, ?, ?)",
            (session['user_id'], title, description, category, status, publish_date)
        )
        db.commit()
        return redirect(url_for('dashboard'))

    return render_template('content_form.html', action="Add New", content=None, default_date=datetime.now().strftime('%Y-%m-%d'))


@app.route('/content/edit/<int:id>', methods=['GET', 'POST'])
def edit_content(id):
    if not is_logged_in(): return redirect(url_for('signin'))
    db = get_db()

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        category = request.form['category']
        status = request.form['status']
        publish_date = request.form['publish_date']

        db.execute(
            "UPDATE contents SET title=?, description=?, category=?, status=?, publish_date=? WHERE id=? AND user_id=?",
            (title, description, category, status, publish_date, id, session['user_id'])
        )
        db.commit()
        return redirect(url_for('dashboard'))

    content = row_to_dict(db.execute(
        "SELECT * FROM contents WHERE id = ? AND user_id = ?", (id, session['user_id'])
    ).fetchone())
    if not content: return "Konten tidak ditemukan", 404

    # publish_date sudah dalam format 'YYYY-MM-DD' sebagai teks

    return render_template('content_form.html', action="Edit", content=content, default_date=datetime.now().strftime('%Y-%m-%d'))


@app.route('/content/delete/<int:id>', methods=['POST'])
def delete_content(id):
    if not is_logged_in(): return jsonify({'success': False}), 401
    db = get_db()
    db.execute("DELETE FROM contents WHERE id = ? AND user_id = ?", (id, session['user_id']))
    db.commit()
    return jsonify({'success': True})


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not is_logged_in(): return redirect(url_for('signin'))

    if request.method == 'POST':
        new_username = request.form['username'].strip()
        user_id = session['user_id']

        db = get_db()
        try:
            existing_user = row_to_dict(db.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?", (new_username, user_id)
            ).fetchone())

            if existing_user:
                flash("Username sudah terdaftar! Silakan gunakan nama lain.", "danger")
            else:
                db.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
                db.commit()

                session['username'] = new_username
                flash("Perubahan profil berhasil disimpan!", "success")
        except Exception:
            flash("Terjadi kesalahan sistem saat menyimpan data.", "danger")

        return redirect(url_for('profile'))

    return render_template('profile.html')


@app.route('/setting', methods=['GET', 'POST'])
def setting():
    if not is_logged_in(): return redirect(url_for('signin'))

    user_id = session['user_id']
    db = get_db()

    # Ambil info tanggal pendaftaran dari database users
    user_data = row_to_dict(db.execute(
        "SELECT created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone())

    # Format tanggal bergabung agar cantik (Contoh: 09 July 2026)
    joined_date = datetime.now().strftime('%d %B %Y')
    if user_data and user_data.get('created_at'):
        try:
            created_dt = datetime.strptime(user_data['created_at'], '%Y-%m-%d %H:%M:%S')
            joined_date = created_dt.strftime('%d %B %Y')
        except ValueError:
            pass

    if request.method == 'POST':
        selected_lang = request.form.get('language', 'id')
        app_notif = request.form.get('app_notification', 'n')

        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_new_password = request.form.get('confirm_new_password', '')

        session['lang'] = selected_lang
        session['app_notification'] = 'y' if app_notif == 'y' else 'n'

        if current_password or new_password or confirm_new_password:
            current_user_db = row_to_dict(db.execute(
                "SELECT password FROM users WHERE id = ?", (user_id,)
            ).fetchone())

            if not current_user_db or not bcrypt.checkpw(current_password.encode('utf-8'), current_user_db['password'].encode('utf-8')):
                msg = "Password saat ini salah!" if selected_lang != 'en' else "Current password is incorrect!"
                flash(msg, "danger")
                return redirect(url_for('setting'))

            if new_password != confirm_new_password:
                msg = "Konfirmasi password baru tidak cocok!" if selected_lang != 'en' else "New password confirmation does not match!"
                flash(msg, "danger")
                return redirect(url_for('setting'))

            if len(new_password) < 6:
                msg = "Password baru minimal harus 6 karakter!" if selected_lang != 'en' else "New password must be at least 6 characters!"
                flash(msg, "danger")
                return redirect(url_for('setting'))

            hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, user_id))
            db.commit()

            password_changed = True
        else:
            password_changed = False

        if selected_lang == 'en':
            msg = "Settings and password updated successfully!" if password_changed else "Settings saved successfully!"
        else:
            msg = "Pengaturan dan password berhasil diperbarui!" if password_changed else "Pengaturan berhasil disimpan!"

        flash(msg, "success")
        return redirect(url_for('setting'))

    return render_template('setting.html', joined_date=joined_date)


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)