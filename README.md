# eptran

İngilizce epub dosyalarını Türkçeye çeviren, Gemini 2.0 Flash destekli araç.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/dpentx/eptran&env=GEMINI_API_KEY,GH_PAT,GH_REPO,GH_BRANCH&envDescription=Kurulum%20için%20gerekli%20değişkenler&envLink=https://github.com/dpentx/eptran/blob/main/.env.example)

## Nasıl Çalışır?

1. epub'u web arayüzünden yüklersin
2. Dosya geçici olarak repona commit edilir, GitHub Actions tetiklenir
3. Actions her bölümü Gemini 2.0 Flash ile çevirir
4. Bölümler `output/` klasörüne yazılır, kaynak dosya silinir
5. Arayüzden çeviri ilerlemesini takip edebilir, tamamlanınca dosyaları indirebilirsin

## Kurulum

### 1. Repoyu Fork'la

Sağ üstten **Fork** butonuna bas.

### 2. GitHub Actions'ı Etkinleştir

Fork'ladıktan sonra **Actions** sekmesine gidip etkinleştir.

### 3. GitHub PAT Oluştur

[github.com/settings/tokens](https://github.com/settings/tokens/new) adresinden:
- **Token adı:** eptran
- **İzinler:** `Contents` (Read and Write), `Actions` (Write)

### 4. Gemini API Key Al

[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) adresinden ücretsiz key oluştur.

### 5. Vercel'e Deploy Et

"Deploy with Vercel" butonuna basıp şu değişkenleri gir:

| Değişken | Açıklama |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key'in |
| `GH_PAT` | 3. adımda oluşturduğun token |
| `GH_REPO` | `kullaniciadi/eptran` formatında fork'un adı |
| `GH_BRANCH` | Branch adı (genellikle `main`) |

### 6. Repo Secret Ekle

GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**:
- İsim: `GEMINI_API_KEY`
- Değer: Gemini API key'in

## Limitler

Gemini 2.0 Flash ücretsiz tier:
- 1 milyon token/gün
- 15 istek/dakika

Ortalama bir roman (~100k kelime) bir günde tamamlanır. Büyük kitaplarda işlem birden fazla güne yayılabilir — Actions otomatik devam eder.

## Çıktı Formatı

Her bölüm `output/kitap-adi/001_kitap-adi.txt` şeklinde kaydedilir.

---

*Gemini 2.0 Flash · GitHub Actions · Vercel*
