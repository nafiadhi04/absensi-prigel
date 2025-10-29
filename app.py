import os
import json 
import base64 
import mysql.connector
# Mengubah import untuk menyertakan render_template
from flask import Flask, request, jsonify, redirect, render_template 
from dotenv import load_dotenv
from datetime import datetime
from deepface import DeepFace


# Muat variabel environment dari file .env
load_dotenv()

# Inisialisasi Aplikasi Flask
# Perlu inisialisasi di sini karena render_template memerlukannya
app = Flask(__name__)

# Konfigurasi folder upload
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Konfigurasi Database (Menggunakan Hardcoded yang sudah terbukti berhasil)
db_config = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '',
    'database': 'absensi_db'
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
@app.route('/halaman_absen')
def halaman_absen():
    # Menggunakan templating: render_template memanggil file templates/absen.html
    return render_template('absen.html')


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
        
        os.remove(temp_snapshot_path)
        
        # 4. Proses Hasil Pencarian
        if not dfs or dfs[0].empty:
            return jsonify({"success": False, "message": "Wajah tidak terdaftar"}), 404
        
        matched_file_path = dfs[0]['identity'][0]
        filename = os.path.basename(matched_file_path)
        nip_cocok = os.path.splitext(filename)[0]
        
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


if __name__ == '__main__':
    # Pastikan folder upload ada
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    # Jalankan server Flask
    app.run(debug=True, port=5000)