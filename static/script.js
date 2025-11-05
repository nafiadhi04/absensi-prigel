// --- Ambil Elemen DOM ---
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const tombolAbsen = document.getElementById('tombolAbsen');
const tombolReset = document.getElementById('tombolReset'); 
const statusDiv = document.getElementById('status');
const hasilAbsensiCard = document.getElementById('hasilAbsensiCard');
const statusOverallDiv = document.getElementById('status-overall');
const hasilWaktuDihabiskanSpan = document.getElementById('hasil_waktu_dihabiskan');

// --- Fungsi Helper ---

/**
 * Mengupdate pesan status di bawah kamera.
 * @param {string} message - Pesan yang ingin ditampilkan.
 * @param {string} type - 'info', 'success', atau 'error'.
 */
function updateStatus(message, type = 'info') {
    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type}`;
}

/**
 * Menghitung durasi antara jam berangkat dan pulang.
 * @param {string} startTimeStr - Cth: "08:00:00"
 * @param {string} endTimeStr - Cth: "17:00:00"
 * @returns {string} - Cth: "9 Jam 0 Menit"
 */
function calculateDuration(startTimeStr, endTimeStr) {
    if (!startTimeStr || !endTimeStr || endTimeStr === 'Belum absen pulang') {
        return 'Belum Penuh';
    }

    const [startHours, startMinutes] = startTimeStr.split(':').map(Number);
    const [endHours, endMinutes] = endTimeStr.split(':').map(Number);
    
    const startDate = new Date();
    startDate.setHours(startHours, startMinutes, 0, 0); 

    const endDate = new Date();
    endDate.setHours(endHours, endMinutes, 0, 0);

    if (endDate < startDate) {
        endDate.setDate(endDate.getDate() + 1);
    }

    const diffMs = endDate - startDate; 
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    return `${diffHours} Jam ${diffMinutes} Menit`;
}

/**
 * Mengatur ulang tampilan ke kondisi awal (standby).
 */
function resetSystem() {
    hasilAbsensiCard.style.display = 'none';
    tombolReset.style.display = 'none';
    tombolAbsen.style.display = 'block';
    tombolAbsen.disabled = false;

    updateStatus("Kamera siap. Hadapkan wajah Anda.", 'info');
}

/**
 * Mengatur tampilan visual saat proses absensi dimulai.
 */
function showProcessingVisuals() {
}

/**
 * Mengatur tampilan visual saat absensi berhasil.
 */
function showSuccessVisuals() {
}

/**
 * Mengatur tampilan visual saat absensi gagal.
 */
function showErrorVisuals() {
}


// --- Logika Utama ---

// 1. Minta akses kamera saat halaman dimuat
navigator.mediaDevices.getUserMedia({ video: true })
    .then(stream => {
        video.srcObject = stream;
        video.onloadedmetadata = () => {
            // Kamera siap, tapi kotak deteksi masih tersembunyi
            updateStatus("Kamera siap. Hadapkan wajah Anda.", 'info');
            console.log("Kamera berhasil dimuat.");
        };
    })
    .catch(err => {
        console.error("Error akses kamera: ", err);
        updateStatus("Error: Tidak bisa mengakses kamera. Pastikan browser memiliki izin.", 'error');
        tombolAbsen.disabled = true; 
    });

// 2. Tombol Absen diklik
tombolAbsen.onclick = function() {
    console.log("Tombol Absen diklik.");
    
    // Tampilkan visual processing
    showProcessingVisuals();
    updateStatus("Memproses absensi...", 'info');
    
    hasilAbsensiCard.style.display = 'none'; 
    tombolAbsen.disabled = true; 
    tombolReset.style.display = 'none'; 

    // Ambil snapshot
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    context.translate(canvas.width, 0); // Pindahkan origin ke kanan atas
    context.scale(-1, 1); // Balik horizontal (cermin)
    context.drawImage(video, 0, 0, canvas.width, canvas.height); // Gambar video yang sudah dibalik
    
    // Kembalikan konteks ke normal (opsional, tapi bagus untuk pemanggilan berikutnya)
    context.setTransform(1, 0, 0, 1, 0, 0);
    
    const dataUrl = canvas.toDataURL('image/jpeg');

    console.log("Request API terkirim ke /api/absen");

    // Kirim snapshot ke API
    fetch('/api/absen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUrl })
    })
    .then(response => {
        console.log("Menerima respons dari server:", response.status);
        if (!response.ok) {
            // Jika server mengembalikan error (cth: 404, 500)
            return response.json().then(errData => {
                throw new Error(errData.message || `Error ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log("Data respons (JSON):", data);
        if (data.success) {
            // --- BERHASIL ---
            updateStatus(`Sukses: ${data.message}`, 'success');
            showSuccessVisuals(); // Tampilkan visual sukses (hijau)
            
            const jamBerangkat = data.data.jam_berangkat;
            const jamPulang = data.data.jam_pulang || 'Belum absen pulang';
            const isPulang = jamPulang !== 'Belum absen pulang';
            
            statusOverallDiv.textContent = isPulang ? "Absen Pulang Berhasil!" : "Absen Masuk Berhasil!";
            statusOverallDiv.className = isPulang ? 'warning' : 'success'; 
            
            hasilAbsensiCard.style.display = 'block';

            document.getElementById('hasil_nama').innerText = data.data.nama;
            document.getElementById('hasil_nip').innerText = data.data.nip;
            document.getElementById('hasil_prodi').innerText = data.data.prodi;
            document.getElementById('hasil_berangkat').innerText = jamBerangkat;
            document.getElementById('hasil_pulang').innerText = jamPulang;
            
            // Perbarui path foto master (pastikan UPLOAD_FOLDER benar)
            document.getElementById('foto_sebelumnya').src = data.data.foto_sebelumnya; 
            
            hasilWaktuDihabiskanSpan.innerText = calculateDuration(jamBerangkat, jamPulang);
            
            // Tampilkan tombol reset
            tombolReset.style.display = 'block';
            tombolAbsen.style.display = 'none';
            
        } else {
            // --- GAGAL (Data tidak sukses) ---
            console.error("Gagal dari API:", data.message);
            updateStatus(`Gagal: ${data.message}`, 'error');
            showErrorVisuals(); // Tampilkan visual error (merah)
            tombolAbsen.disabled = false; // Izinkan coba lagi
        }
    })
    .catch(err => {
        // --- GAGAL (Error Jaringan / Server) ---
        console.error('Error Fetch:', err);
        updateStatus(`Error Kritis: ${err.message}`, 'error');
        showErrorVisuals();
        tombolAbsen.disabled = false; // Izinkan coba lagi
    })
    .finally(() => {
        // Logika finally (jika ada)
        // Di sini kita tidak mengaktifkan tombol reset kecuali jika berhasil
        if (hasilAbsensiCard.style.display === 'block') {
             tombolReset.style.display = 'block';
             tombolAbsen.style.display = 'none';
        } else {
            // Jika gagal, tombol absen sudah di-enable di blok catch/else
        }
    });
};

// 3. Tombol Reset diklik
tombolReset.onclick = function() {
    resetSystem();
}

// Panggil reset saat halaman dimuat untuk memastikan status awal
window.onload = resetSystem;

