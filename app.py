import os
import json 
import base64 
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime
from datetime import datetime
from flask import Flask, request, jsonify, redirect
from deepface import DeepFace


# Muat variabel environment dari file .env
load_dotenv()

# Inisialisasi Aplikasi Flask
app = Flask(__name__)

# Konfigurasi folder upload
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Konfigurasi Database
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

@app.route('/')
def index():
    return """
    <h2>Form Registrasi Pengguna</h2>
    <form action="/register" method="POST" enctype="multipart/form-data">
        NIP: <input type="text" name="nip"><br>
        Nama: <input type="text" name="nama_lengkap"><br>
        Prodi: <input type="text" name="prodi"><br>

        Foto: <input type="file" name="foto" accept="image/*"><br>
        <input type="submit" value="Daftar">
    </form>
    """

# --- API UNTUK REGISTRASI PENGGUNA ---
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
    # Kita gunakan NIP sebagai nama file agar unik
    filename = f"{nip}.jpg"
    path_foto_master = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path_foto_master)

    try:
        # 3. Buat embedding wajah menggunakan DeepFace
        # Ini adalah proses AI-nya
        embedding_objs = DeepFace.represent(
            img_path=path_foto_master,
            model_name='VGG-Face',  # Model yg umum digunakan
            enforce_detection=True # Pastikan wajah terdeteksi
        )
        
        # Ambil vektor embedding-nya
        embedding_wajah = embedding_objs[0]['embedding']
        
        # Ubah list embedding menjadi string JSON untuk disimpan di DB (tipe TEXT)
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
        # Jika terjadi error (misal: wajah tidak terdeteksi oleh DeepFace)
        # Hapus file foto yang sudah ter-upload agar tidak jadi sampah
        if os.path.exists(path_foto_master):
            os.remove(path_foto_master)
            
        return jsonify({
            "success": False, 
            "message": f"Registrasi gagal: {str(e)}"
        }), 500

# --- API UNTUK PROSES ABSENSI ---
@app.route('/api/absen', methods=['POST'])
def proses_absen():
    # 1. Ambil data gambar base64 dari frontend
    data = request.json
    if 'image' not in data:
        return jsonify({"success": False, "message": "Tidak ada data gambar"}), 400

    # 2. Decode gambar Base64
    # Gambar base64 biasanya punya prefix 'data:image/jpeg;base64,' yg perlu dibuang
    try:
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        
        # Simpan sementara snapshot untuk dianalisis
        temp_snapshot_path = "static/temp_absen.jpg"
        with open(temp_snapshot_path, 'wb') as f:
            f.write(image_bytes)
            
    except Exception as e:
        return jsonify({"success": False, "message": f"Error decoding gambar: {str(e)}"}), 400

    # 3. Cari wajah di database (folder) menggunakan DeepFace.find
    db_folder = app.config['UPLOAD_FOLDER']
    try:
        # DeepFace.find akan mencari 'temp_snapshot_path' di dalam 'db_folder'
        dfs = DeepFace.find(
            img_path=temp_snapshot_path,
            db_path=db_folder,
            model_name='VGG-Face',  
            enforce_detection=False # Tidak perlu deteksi wajah lagi (sudah di snapshot)
        )
        
        # Hapus file snapshot sementara
        os.remove(temp_snapshot_path)
        
        # 4. Proses Hasil Pencarian
        # dfs (DataFrame) berisi daftar file yang cocok, diurutkan dari yg paling mirip
        if not dfs or dfs[0].empty:
            return jsonify({"success": False, "message": "Wajah tidak terdaftar"}), 404
        
        # Ambil file yang paling cocok (baris pertama)
        matched_file_path = dfs[0]['identity'][0]
        
        # Ekstrak NIP dari nama file (cth: 'static/uploads/12345.jpg' -> '12345')
        filename = os.path.basename(matched_file_path)
        nip_cocok = os.path.splitext(filename)[0]
        
    except Exception as e:
        # Error jika wajah di snapshot tidak terdeteksi
        os.remove(temp_snapshot_path)
        return jsonify({"success": False, "message": f"Wajah tidak terdeteksi di snapshot: {str(e)}"}), 400

    # 5. Logika Database Absensi
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) # dictionary=True agar hasil SELECT jadi key-value

        # Dapatkan ID pengguna dari NIP yang cocok
        cursor.execute("SELECT id FROM pengguna WHERE nip = %s", (nip_cocok,))
        pengguna = cursor.fetchone()
        
        if not pengguna:
            return jsonify({"success": False, "message": "Data pengguna tidak ditemukan di DB"}), 404
        
        id_cocok = pengguna['id']
        
        # Dapatkan tanggal dan waktu server
        tanggal_ini = datetime.now().strftime("%Y-%m-%d")
        waktu_ini = datetime.now().strftime("%H:%M:%S")
        
        # Ini adalah query ajaib (INSERT ... ON DUPLICATE KEY UPDATE)
        # Jika belum ada data (pengguna_id, tanggal), ia akan INSERT (absen masuk)
        # Jika sudah ada, ia akan UPDATE (absen pulang)
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
            p.nama_lengkap, 
            p.nip, 
            p.prodi, 
            p.path_foto_master,
            a.jam_berangkat, 
            a.jam_pulang
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
                "jam_berangkat": str(data_absen['jam_berangkat']), # Ubah ke string agar aman di JSON
                "jam_pulang": str(data_absen['jam_pulang']) if data_absen['jam_pulang'] else None
            }
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500
    
# --- HALAMAN TESTING UNTUK ABSENSI ---
@app.route('/halaman_absen')
def halaman_absen():
    # Ini adalah HTML, CSS, dan JavaScript dalam satu string Python
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Halaman Absensi</title>
        <style>
            body { font-family: sans-serif; display: grid; place-items: center; min-height: 90vh; }
            #container { display: flex; gap: 20px; align-items: start; }
            #kamera_box, #hasil_box { border: 1px solid #ccc; padding: 20px; border-radius: 8px; }
            video { width: 400px; border-radius: 8px; }
            button { width: 100%; padding: 10px; font-size: 16px; background-color: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background-color: #0056b3; }
            #hasil { margin-top: 15px; }
            #foto_sebelumnya { max-width: 200px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <h1>Absensi Wajah</h1>
        <div id="container">
            <div id="kamera_box">
                <video id="video" autoplay playsinline></video>
                <button id="tombolAbsen">Ambil Absen</button>
            </div>
            <div id="hasil_box">
                <strong>Hasil:</strong>
                <div id="status">Silakan hadapkan wajah ke kamera...</div>
                <div id="hasil" style="display:none;">
                    <h3 id="hasil_nama"></h3>
                    <p>NIP: <span id="hasil_nip"></span></p>
                    <p>Prodi: <span id="hasil_prodi"></span></p>
                    <p>Jam Berangkat: <span id="hasil_berangkat"></span></p>
                    <p>Jam Pulang: <span id="hasil_pulang"></span></p>
                    <p>Foto Referensi:</p>
                    <img id="foto_sebelumnya" src="" alt="Foto Referensi">
                </div>
            </div>
        </div>
        <canvas id="canvas" style="display:none;"></canvas>

        <script>
            const video = document.getElementById('video');
            const canvas = document.getElementById('canvas');
            const tombolAbsen = document.getElementById('tombolAbsen');
            const statusDiv = document.getElementById('status');
            const hasilDiv = document.getElementById('hasil');

            // 1. Minta akses kamera
            navigator.mediaDevices.getUserMedia({ video: true })
                .then(stream => {
                    video.srcObject = stream;
                })
                .catch(err => {
                    console.error("Error akses kamera: ", err);
                    statusDiv.innerHTML = "Error: Tidak bisa mengakses kamera.";
                });

            // 2. Saat tombol diklik
            tombolAbsen.onclick = function() {
                statusDiv.innerHTML = "Memproses...";
                hasilDiv.style.display = 'none';

                // 3. Ambil snapshot
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
                
                // 4. Ubah snapshot ke Base64
                const dataUrl = canvas.toDataURL('image/jpeg');

                // 5. Kirim ke API Backend
                fetch('/api/absen', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: dataUrl })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // 6. Tampilkan data jika sukses
                        statusDiv.innerHTML = `<strong style="color:green;">${data.message}</strong>`;
                        hasilDiv.style.display = 'block';
                        document.getElementById('hasil_nama').innerText = data.data.nama;
                        document.getElementById('hasil_nip').innerText = data.data.nip;
                        document.getElementById('hasil_prodi').innerText = data.data.prodi;
                        document.getElementById('hasil_berangkat').innerText = data.data.jam_berangkat;
                        document.getElementById('hasil_pulang').innerText = data.data.jam_pulang || 'Belum absen pulang';
                        // Tambahkan / di depan path agar browser tahu itu dari root
                        document.getElementById('foto_sebelumnya').src = '/' + data.data.foto_sebelumnya; 
                    } else {
                        // 7. Tampilkan error jika gagal
                        statusDiv.innerHTML = `<strong style="color:red;">Gagal: ${data.message}</strong>`;
                        hasilDiv.style.display = 'none';
                    }
                })
                .catch(err => {
                    console.error('Error Fetch:', err);
                    statusDiv.innerHTML = "Error komunikasi dengan server.";
                });
            };
        </script>
    </body>
    </html>
    """


if __name__ == '__main__':
    # Pastikan folder upload ada
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    # Jalankan server Flask
    app.run(debug=True, port=5000)