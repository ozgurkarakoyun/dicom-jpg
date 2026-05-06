# DICOM → JPG Railway Web App

Bu uygulama, kullanıcı tarafından yüklenen DICOM dosyalarını veya ZIP arşivlerini JPG formatına çevirir ve sonuçları ZIP olarak indirmeye izin verir.

## Özellikler

- Çoklu DICOM dosyası yükleme
- ZIP olarak CD içeriği yükleme
- DICOM tarih bilgisine göre klasörleme
- JPG çıktı üretme
- Tüm JPG çıktıları tek ZIP olarak indirme
- Tek tek JPG indirme
- Basit işlem arşivi
- Railway uyumlu Flask + Gunicorn yapılandırması

## Lokal kurulum

```bash
pip install -r requirements.txt
python app.py
```

Tarayıcıda aç:

```text
http://localhost:5000
```

## Railway kurulumu

1. GitHub'da yeni bir repo oluştur.
2. Bu dosyaları repoya yükle.
3. Railway'de **New Project → Deploy from GitHub Repo** seç.
4. Repoyu seç.
5. Railway otomatik olarak `Procfile` içindeki komutla uygulamayı çalıştırır.

## Railway Environment Variables

Önerilen değişkenler:

```text
SECRET_KEY=uzun-rastgele-bir-anahtar
MAX_UPLOAD_MB=500
DATA_DIR=/data
```

Kalıcı arşiv istiyorsanız Railway'de Volume ekleyin ve mount path olarak:

```text
/data
```

kullanın.

Volume kullanmazsanız Railway'in geçici dosya sistemi nedeniyle eski yüklemeler silinebilir.

## Kullanım

- DICOM dosyalarını tek tek seçebilirsiniz.
- CD içeriğini önce ZIP yapıp tek dosya olarak yükleyebilirsiniz.
- Çıktılar tarih/study/seri klasörlerine ayrılır.
- Sonuç sayfasından tüm JPG'leri ZIP olarak indirebilirsiniz.

## Önemli not

DICOM dosyaları hasta verisi içerebilir. Bu sistemi herkese açık kullanacaksanız:
- Giriş/şifre sistemi ekleyin.
- HTTPS kullanın.
- DICOM metadata anonimleştirme ekleyin.
- Yüklenen dosyaları otomatik silme süresi tanımlayın.


## Railway build hatası düzeltmesi

Eğer şu hatayı görürseniz:

```text
ResolutionImpossible
pylibjpeg-libjpeg depends on numpy<3.0 and >=2.0
The user requested numpy==1.26.4
```

`requirements.txt` içindeki numpy satırı şu şekilde olmalıdır:

```text
numpy>=2.0,<3.0
```

Bu paket kombinasyonu Railway Python 3.11 ortamı için uyumludur.


## Klasör yükleme

Bu sürümde tek dosya yerine doğrudan klasör seçilebilir.

Kullanım:

1. CD içeriğini bilgisayarda bir klasöre kopyalayın.
2. Web uygulamasında **Klasör yükle** bölümünden ana klasörü seçin.
3. Sistem tüm alt klasörleri tarar.
4. DICOM olan dosyaları otomatik algılar.
5. JPG çıktıları tarih / çalışma / seri klasörlerine ayrılır.
6. Sonuçları tek ZIP olarak indirebilirsiniz.

Not: Klasör yükleme özelliği Chrome ve Edge üzerinde en sorunsuz çalışır.
Firefox veya Safari desteklemezse klasörü ZIP yapıp yükleyin.
