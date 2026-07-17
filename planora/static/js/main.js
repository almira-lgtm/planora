// 1. Fungsi pencarian & filter gabungan untuk halaman MY CONTENT (Tetap dipertahankan & diamankan)
function filterAllContent() {
    const status = document.getElementById('statusFilter').value;
    const search = document.getElementById('searchBar').value;
    
    // Kita tambahkan parameter status agar backend Flask tahu kita memfilter secara umum, bukan bulanan dashboard
    fetch(`/api/contents?status=${status}&search=${search}`)
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById('all-contents-container');
            if(!container) return; // Mencegah error jika dijalankan di halaman selain My Content
            
            container.innerHTML = '';
            
            if(data.length === 0) {
                container.innerHTML = '<p style="color:#999; padding:20px; text-align:center; font-style:italic;">Konten tidak ditemukan atau workspace kosong.</p>';
                return;
            }
            
            data.forEach(item => {
                // Menangani penulisan kelas status 'In Progress' agar tidak terpecah spasi di CSS class
                const statusClass = item.status.toLowerCase().replace(' ', '-');

                container.innerHTML += `
                    <div class="content-item">
                        <div>
                            <strong>${item.title}</strong> <span class="badge ${statusClass}">${item.status}</span><br>
                            <small style="color:#777">${item.category} · Distribusi: 📅 ${item.publish_date}</small>
                            <p style="margin: 5px 0 0 0; font-size: 14px; color: #444;">${item.description || 'Tidak ada deskripsi.'}</p>
                        </div>
                        <div style="min-width: 120px; text-align: right;">
                            <a href="/content/edit/${item.id}" style="text-decoration:none; margin-right:10px; color: #0052cc;">✏️ Edit</a>
                            <a href="#" onclick="deleteContent(${item.id})" style="text-decoration:none; color:red;">🗑️ Hapus</a>
                        </div>
                    </div>
                `;
            });
        });
}

// 2. Fungsi hapus konten (Digunakan bersama di Dashboard & My Content)
function deleteContent(id) {
    if(confirm('Apakah Anda yakin ingin menghapus konten ini secara permanen?')) {
        fetch(`/content/delete/${id}`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    alert('Konten sukses dihapus!');
                    location.reload(); // Muat ulang halaman otomatis agar angka statistik diperbarui
                }
            });
    }
}

// Otomatis jalankan pencarian pertama kali saat halaman My Content dibuka
document.addEventListener("DOMContentLoaded", function() {
    if (document.getElementById('all-contents-container')) {
        filterAllContent();
    }
});