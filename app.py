import os
import json 
import base64 
import mysql.connector
import numpy as np # Diperlukan untuk warm up
from flask import Flask, request, jsonify, redirect, render_template 
from dotenv import load_dotenv
from datetime import datetime
from deepface import DeepFace


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
# Disesuaikan: Mendefinisikan static_folder dan static_url_path secara eksplisit untuk mengatasi 404
app = Flask(__name__, static_folder='static', static_url_path='/static')

# Konfigurasi folder upload
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Konfigurasi database MySQL menggunakan variabel environment
db_config = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

def get_db_connection():
    """Mendapatkan koneksi ke database MySQL."""
    conn = mysql.connector.connect(**db_config)
    return conn

## 🌐 ROUTE 1: HALAMAN REGISTRASI (FORM UTAMA)
@app.route('/')
def index():
    # Menggunakan templating: render_template memanggil file templates/register.html
    return render_template('register.html')


## 🌐 ROUTE 2: API UNTUK REGISTRASI PENGGUNA (PROSES FORM)
@app.route('/register', methods=['POST'])
def register_user():
    # 1. Ambil data dari form-data
    if 'foto' not in request.files:
        return jsonify({"success": False, "message": "File foto tidak ditemukan"}), 400
    
    file = request.files['foto']
    nip = request.form['nip']
    nama = request.form['nama_lengkap']
    prodi = request.form['prodi']
    
    if file.filename == '':
        return jsonify({"success": False, "message": "Nama file foto kosong"}), 400

    # 2. Simpan file foto ke server
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

        # 4. Simpan data ke database
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
        # Hapus file foto jika gagal
        if os.path.exists(path_foto_master):
            os.remove(path_foto_master)
            
        return jsonify({
            "success": False, 
            "message": f"Registrasi gagal: {str(e)}"
        }), 500

## 🌐 ROUTE 3: HALAMAN ABSENSI
@app.route('/halaman_absen')  # <-- UBAH INI
def halaman_absen():
    # Menggunakan templating: render_template memanggil file templates/absen.html
    return render_template('absen.html')

@app.route('/admin')
def admin_dashboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) # dictionary=True agar mudah diakses

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

        # Query 2: Ambil semua pengguna terdaftar
        cursor.execute("SELECT nip, nama_lengkap, prodi, path_foto_master FROM pengguna ORDER BY nama_lengkap ASC;")
        data_pengguna = cursor.fetchall()

        cursor.close()
        conn.close()

        # Kirim kedua list data ke file HTML
        return render_template('admin.html', 
                            logs=data_absensi, 
                            users=data_pengguna)
    
    except Exception as e:
        return f"Terjadi error: {str(e)}", 500


## 🌐 ROUTE 4: API PROSES ABSENSI (DIPANGGIL DARI JAVASCRIPT DI absen.html)
@app.route('/api/absen', methods=['POST'])
def proses_absen():
    # 1. Ambil data gambar base64 dari frontend
    data = request.json
    if 'image' not in data:
        return jsonify({"success": False, "message": "Tidak ada data gambar"}), 400

    # 2. Decode gambar Base64 dan simpan sementara
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        
        temp_snapshot_path = "static/temp_absen.jpg"
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
            return jsonify({"success": False, "message": "Wajah tidak terdaftar"}), 404
        
        # Ambil path file yang paling cocok (baris pertama dari DataFrame pertama)
        matched_file_path = dfs[0]['identity'].iloc[0]
        filename = os.path.basename(matched_file_path)
        nip_cocok = os.path.splitext(filename)[0]

        # -----------------------------------------------------------------
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
        # -----------------------------------------------------------------
        
    except Exception as e:
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
        
        # Query INSERT ... ON DUPLICATE KEY UPDATE
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
        pdf = FPDF(orientation='L', unit='mm', format='A4') # 'L' = Landscape
        pdf.add_page()
        
        # 3. Judul
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Laporan Log Absensi', 0, 1, 'C')
        
        # 4. Sub-judul (Tanggal Cetak)
        tanggal_hari_ini = datetime.now().strftime("%d %B %Y")
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f'Dicetak pada: {tanggal_hari_ini}', 0, 1, 'C')
        pdf.ln(5) # Spasi

        # 5. Header Tabel
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(240, 240, 240) # Latar abu-abu
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


if __name__ == '__main__':
    # Pastikan folder upload ada
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    # Panggil fungsi warm-up (memuat model) sebelum server berjalan
    warm_up_deepface()
    
    # Jalankan server Flask
    app.run(debug=True, port=5000)

