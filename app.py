import os
import json
import base64
import mysql.connector
import numpy as np  # Diperlukan untuk warm up
from flask import Flask, request, jsonify, redirect, render_template, Response, session, url_for
from fpdf import FPDF
from dotenv import load_dotenv
from datetime import datetime
from deepface import DeepFace
from werkzeug.security import check_password_hash

# Muat variabel environment dari file .env
load_dotenv()

# --- FUNGSI WARM-UP DEEPFACE ---
def warm_up_deepface():
    """
    Memuat model DeepFace (VGG-Face) ke memori saat server pertama kali dijalankan.
    Ini untuk mengatasi 'cold start' atau loading lama pada panggilan API pertama.
    """
    try:
        print("INFO: Memulai Warm-Up DeepFace (Model VGG-Face)...")
        # Membuat gambar dummy (array numpy) untuk memicu pemuatan model
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        # Menggunakan model 'VGG-Face' yang sama dengan yang digunakan di API
        DeepFace.represent(
            img_path=dummy_image,
            model_name='VGG-Face',
            enforce_detection=False
        )
        print("INFO: Warm-Up DeepFace Selesai. Model siap.")
    except Exception as e:
        print(f"ERROR saat Warm-Up DeepFace: {str(e)}")
# ---------------------------------

# Inisialisasi Aplikasi Flask
app = Flask(__name__, static_folder='static', static_url_path='/static')

# Secret key: ambil dari environment kalau ada, kalau tidak pakai fallback dev (ganti di prod!)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev_secret_key')

# Konfigurasi folder upload
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Konfigurasi database MySQL menggunakan variabel environment
db_config = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'absensi_db')
}

def get_db_connection():
    """Mendapatkan koneksi ke database MySQL (mysql.connector)."""
    conn = mysql.connector.connect(**db_config)
    return conn

def verify_password(stored_password, provided_password):
    """
    Verifikasi password:
    - Jika stored_password tampak seperti hash (werkzeug compatible), gunakan check_password_hash
    - Jika tidak, fallback ke perbandingan plaintext (untuk data legacy)
    """
    try:
        # coba check_password_hash; jika stored_password bukan hash yang dikenali,
        # check_password_hash akan mengembalikan False (tidak error).
        if stored_password and check_password_hash(stored_password, provided_password):
            return True
    except Exception:
        # ignore dan coba fallback
        pass

    # fallback: bandingkan langsung (tidak aman, hanya untuk backward compatibility)
    return stored_password == provided_password

# ------------------ ROUTES ------------------

## Halaman Registrasi (form utama)
@app.route('/')
def index():
    return render_template('register.html')

## API Registrasi Pengguna (form)
@app.route('/register', methods=['POST'])
def register_user():
    if 'foto' not in request.files:
        return jsonify({"success": False, "message": "File foto tidak ditemukan"}), 400

    file = request.files['foto']
    nip = request.form.get('nip', '').strip()
    nama = request.form.get('nama_lengkap', '').strip()
    prodi = request.form.get('prodi', '').strip()

    if not nip:
        return jsonify({"success": False, "message": "NIP wajib diisi"}), 400

    if file.filename == '':
        return jsonify({"success": False, "message": "Nama file foto kosong"}), 400

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filename = f"{nip}.jpg"
    path_foto_master = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path_foto_master)

    try:
        # 3. Buat embedding wajah menggunakan DeepFace
        embedding_objs = DeepFace.represent(
            img_path=path_foto_master,
            model_name='VGG-Face',
            enforce_detection=True
        )

        embedding_wajah = embedding_objs[0]['embedding']
        embedding_json = json.dumps(embedding_wajah)

        # 4. Simpan data pengguna ke database
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
        INSERT INTO pengguna (nip, nama_lengkap, prodi, path_foto_master, embedding_wajah)
        VALUES (%s, %s, %s, %s, %s)
        """
        values = (nip, nama, prodi, path_foto_master, embedding_json)

        cursor.execute(query, values)
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"Pengguna {nama} berhasil terdaftar!"
        }), 201

    except Exception as e:
        # Hapus file foto jika gagal registrasi
        if os.path.exists(path_foto_master):
            os.remove(path_foto_master)

        return jsonify({
            "success": False,
            "message": f"Registrasi gagal: {str(e)}"
        }), 500

## 🌐 ROUTE 3: HALAMAN ABSENSI
@app.route('/halaman_absen')
def halaman_absen():
    # Menggunakan templating: render_template memanggil file templates/absen.html
    return render_template('absen.html')

## Admin login (MySQL)
@app.route('/admin_login', methods=['GET', 'POST'])
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # DEBUG PRINT
        print(f"--- DEBUG LOGIN ---")
        print(f"Username input: {username}")
        print(f"Password input: {password}")

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Cek koneksi DB
            print(f"Koneksi DB: {conn.database}") 

            cursor.execute("SELECT * FROM admin WHERE username = %s", (username,))
            row = cursor.fetchone()
            
            # DEBUG PRINT HASIL DB
            print(f"Data user dari DB: {row}") 

            cursor.close()
            conn.close()
        except Exception as e:
            row = None
            error = f"Database error: {str(e)}"
            print(f"ERROR: {error}") # Print error ke terminal

        if not row:
            error = error or "Username tidak ditemukan."
            return render_template('admin_login.html', error=error)

        stored_password = row.get('password')
        
        # DEBUG CHECK PASSWORD
        cek_pass = verify_password(stored_password, password)
        print(f"Password Database: {stored_password}")
        print(f"Hasil Verifikasi: {cek_pass}")

        if cek_pass:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Password salah."
            return render_template('admin_login.html', error=error)

    return render_template('admin_login.html', error=error)

@app.route('/admin_logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

## Admin dashboard (protected)
@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query 1: Ambil semua log absensi, di-join dengan nama pengguna
        # Diurutkan dari yang terbaru
        query_log = """
        SELECT 
            p.nama_lengkap, p.nip, p.prodi,
            a.tanggal, a.jam_berangkat, a.jam_pulang
        FROM absensi a
        JOIN pengguna p ON a.pengguna_id = p.id
        ORDER BY a.tanggal DESC, a.jam_berangkat DESC;
        """
        cursor.execute(query_log)
        data_absensi = cursor.fetchall()

        # Query 2: Ambil semua data pengguna
        cursor.execute("SELECT nip, nama_lengkap, prodi, path_foto_master FROM pengguna ORDER BY nama_lengkap ASC;")
        data_pengguna = cursor.fetchall()

        cursor.close()
        conn.close()

        # Kirim kedua list data ke file HTML admin.html
        return render_template('admin.html', logs=data_absensi, users=data_pengguna)

    except Exception as e:
        return f"Terjadi error: {str(e)}", 500

## API proses absen (frontend -> backend)
@app.route('/api/absen', methods=['POST'])
def proses_absen():
    # 1. Ambil data gambar base64 dari frontend
    data = request.json
    if not data or 'image' not in data:
        return jsonify({"success": False, "message": "Tidak ada data gambar"}), 400

    # 2. Decode gambar Base64 dan simpan sementara
    try:
        image_data = data['image'].split(',')[1] if ',' in data['image'] else data['image']
        image_bytes = base64.b64decode(image_data)

        temp_snapshot_path = "static/temp_absen.jpg"
        os.makedirs(os.path.dirname(temp_snapshot_path), exist_ok=True)
        with open(temp_snapshot_path, 'wb') as f:
            f.write(image_bytes)

    except Exception as e:
        return jsonify({"success": False, "message": f"Error decoding gambar: {str(e)}"}), 400

    # 3. Cari wajah di database (folder) menggunakan DeepFace.find
    db_folder = app.config['UPLOAD_FOLDER']
    try:
        dfs = DeepFace.find(
            img_path=temp_snapshot_path,
            db_path=db_folder,
            model_name='VGG-Face',
            enforce_detection=False
        )
        # MODIFIKASI: Jangan hapus file temp di sini
        # os.remove(temp_snapshot_path) <-- BARIS INI DIHAPUS

        # 4. Proses Hasil Pencarian
        if not dfs or dfs[0].empty:
            if os.path.exists(temp_snapshot_path):
                os.remove(temp_snapshot_path)
            return jsonify({"success": False, "message": "Wajah tidak terdaftar"}), 404

        # Ambil path file yang paling cocok (baris pertama dari DataFrame pertama)
        matched_file_path = dfs[0]['identity'].iloc[0]
        filename = os.path.basename(matched_file_path)
        nip_cocok = os.path.splitext(filename)[0]

        # MODIFIKASI: GANTI FOTO LAMA DENGAN SNAPSHOT BARU
        # Pindahkan file snapshot (temp_snapshot_path) untuk menimpa
        # file foto master (matched_file_path) yang cocok.
        try:
            os.replace(temp_snapshot_path, matched_file_path)
        except OSError as e:
            # Jika gagal memindahkan file, setidaknya hapus file temp
            if os.path.exists(temp_snapshot_path):
                os.remove(temp_snapshot_path)
            return jsonify({"success": False, "message": f"Gagal update foto: {str(e)}"}), 500

    except Exception as e:
        if os.path.exists(temp_snapshot_path):
            os.remove(temp_snapshot_path)
        return jsonify({"success": False, "message": f"Wajah tidak terdeteksi di snapshot: {str(e)}"}), 400

    # 5. Logika Database Absensi
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id FROM pengguna WHERE nip = %s", (nip_cocok,))
        pengguna = cursor.fetchone()

        if not pengguna:
            return jsonify({"success": False, "message": "Data pengguna tidak ditemukan di DB"}), 404

        id_cocok = pengguna['id']
        tanggal_ini = datetime.now().strftime("%Y-%m-%d")
        waktu_ini = datetime.now().strftime("%H:%M:%S")

        # Query INSERT ... ON DUPLICATE KEY UPDATE untuk log absensi
        query_log = """
        INSERT INTO absensi (pengguna_id, tanggal, jam_berangkat)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            jam_pulang = %s;
        """
        cursor.execute(query_log, (id_cocok, tanggal_ini, waktu_ini, waktu_ini))
        conn.commit()

        # 6. Ambil data lengkap untuk ditampilkan di frontend
        query_data = """
        SELECT 
            p.nama_lengkap, p.nip, p.prodi, p.path_foto_master,
            a.jam_berangkat, a.jam_pulang
        FROM 
            absensi a
        JOIN 
            pengguna p ON a.pengguna_id = p.id
        WHERE 
            a.pengguna_id = %s AND a.tanggal = %s;
        """
        cursor.execute(query_data, (id_cocok, tanggal_ini))
        data_absen = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Absen Berhasil!",
            "data": {
                "nama": data_absen['nama_lengkap'],
                "nip": data_absen['nip'],
                "prodi": data_absen['prodi'],
                "foto_sebelumnya": data_absen['path_foto_master'],
                "jam_berangkat": str(data_absen['jam_berangkat']),
                "jam_pulang": str(data_absen['jam_pulang']) if data_absen['jam_pulang'] else None
            }
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

## 🌐 ROUTE 6: DOWNLOAD LOG ABSENSI (PDF)
@app.route('/admin/download_pdf')
def download_pdf():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    try:
        # 1. Ambil data log absensi (SAMA SEPERTI SEBELUMNYA)
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query_log = """
        SELECT 
            p.nama_lengkap, p.nip, p.prodi,
            a.tanggal, a.jam_berangkat, a.jam_pulang
        FROM absensi a
        JOIN pengguna p ON a.pengguna_id = p.id
        ORDER BY a.tanggal DESC, a.jam_berangkat DESC;
        """
        cursor.execute(query_log)
        data_absensi = cursor.fetchall()
        cursor.close()
        conn.close()

        # 2. Buat PDF secara manual dengan FPDF2
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()

        # 3. Judul dan Header
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Laporan Log Absensi', 0, 1, 'C')

        # 4. Sub-judul (Tanggal Cetak)
        tanggal_hari_ini = datetime.now().strftime("%d %B %Y")
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f'Dicetak pada: {tanggal_hari_ini}', 0, 1, 'C')
        pdf.ln(5) # Spasi

        # 5. Header Tabel
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(240, 240, 240)
        col_width_tanggal = 30
        col_width_nip = 30
        col_width_nama = 70
        col_width_prodi = 60
        col_width_jam = 40

        pdf.cell(col_width_tanggal, 10, 'Tanggal', 1, 0, 'C', fill=True)
        pdf.cell(col_width_nip, 10, 'NIP', 1, 0, 'C', fill=True)
        pdf.cell(col_width_nama, 10, 'Nama Lengkap', 1, 0, 'C', fill=True)
        pdf.cell(col_width_prodi, 10, 'Prodi', 1, 0, 'C', fill=True)
        pdf.cell(col_width_jam, 10, 'Jam Berangkat', 1, 0, 'C', fill=True)
        pdf.cell(col_width_jam, 10, 'Jam Pulang', 1, 1, 'C', fill=True)

        # 6. Isi Tabel (Data Log)
        pdf.set_font('Arial', '', 9)
        if not data_absensi:
            pdf.cell(0, 10, 'Tidak ada data absensi.', 1, 1, 'C')
        else:
            for log in data_absensi:
                pdf.cell(col_width_tanggal, 10, str(log['tanggal']), 1, 0, 'C')
                pdf.cell(col_width_nip, 10, log['nip'], 1, 0, 'L')
                pdf.cell(col_width_nama, 10, log['nama_lengkap'], 1, 0, 'L')
                pdf.cell(col_width_prodi, 10, log['prodi'] or '-', 1, 0, 'L')
                pdf.cell(col_width_jam, 10, str(log['jam_berangkat'] or '-'), 1, 0, 'C')
                pdf.cell(col_width_jam, 10, str(log['jam_pulang'] or '-'), 1, 1, 'C')

        # 7. Siapkan file PDF untuk di-download
        pdf_output = bytes(pdf.output(dest='B'))
        nama_file_pdf = f"Log_Absensi_{datetime.now().strftime('%Y-%m-%d')}.pdf"

        # 8. Kirim file PDF sebagai respons
        return Response(
            pdf_output,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename={nama_file_pdf}'
            }
        )

    except Exception as e:
        return f"Terjadi error saat membuat PDF: {str(e)}", 500
    
# --- TAMBAHAN: MENCEGAH CACHE BROWSER (AGAR TOMBOL BACK TIDAK BISA DIPAKAI SETELAH LOGOUT) ---
@app.after_request
def add_header(response):
    """
    Menambahkan header ke setiap respons agar browser tidak menyimpan cache halaman.
    """
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

if __name__ == '__main__':
    # Pastikan folder upload ada
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Panggil fungsi warm-up (memuat model) sebelum server berjalan
    warm_up_deepface()

    # Jalankan server Flask
    app.run(debug=True, port=5000)
