# eptran

İngilizce epub dosyalarını Türkçeye çeviren, Groq llama-3.3-70b destekli araç.

## Nasıl Çalışır?

1. epub'u web arayüzünden yüklersin
2. Dosya repona commit edilir, GitHub Actions tetiklenir
3. Actions her bölümü Groq llama-3.3-70b ile çevirir
4. Çeviri tamamlanınca bölümler epub olarak paketlenir
5. Arayüzden ilerlemeyi takip edebilir, tamamlanınca indirebilirsin

## Kurulum

### 1. Repoyu Fork'la

Sağ üstten **Fork** butonuna bas.

### 2. GitHub Actions'ı Etkinleştir

Fork'ladıktan sonra **Actions** sekmesine gidip etkinleştir.

### 3. GitHub PAT Oluştur

[github.com/settings/tokens](https://github.com/settings/tokens/new) adresinden:
- **Token adı:** eptran
- **İzinler:** `Contents` (Read and Write), `Actions` (Write)

### 4. Groq API Key Al

[console.groq.com](https://console.groq.com) adresinden ücretsiz key oluştur.

### 5. Vercel'e Deploy Et

[vercel.com](https://vercel.com) üzerinden repoyu import et ve şu ortam değişkenlerini gir:

| Değişken | Açıklama |
|---|---|
| `GH_PAT` | 3. adımda oluşturduğun token |
| `GH_REPO` | `kullaniciadi/eptran` formatında fork'un adı |
| `GH_BRANCH` | Branch adı (genellikle `main`) |

### 6. Repo Secret Ekle

GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**:
- İsim: `GROQ_API_KEY`
- Değer: Groq API key'in

## Limitler

Groq ücretsiz tier (llama-3.3-70b-versatile):
- 14,400 token/gün
- Büyük kitaplarda çeviri birden fazla güne yayılabilir
- Actions her 6 saatte bir otomatik devam eder

## Çıktı Formatı

Çeviri tamamlanınca `output/kitap-adi/kitap-adi_tr.epub` olarak indirilir.
Bölümler ayrıca `output/kitap-adi/001_kitap-adi.txt` şeklinde de mevcuttur.

---

*Groq llama-3.3-70b · GitHub Actions · Vercel*
