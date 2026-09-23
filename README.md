# Control MySQL Services

أداة ويندوز في System Tray للتحكم في خدمات ونسخ MySQL (Windows Services + Laragon / XAMPP).

**فاتوس للبرمجيات — [vatoce.com](https://vatoce.com)**

## المتطلبات

- Windows 10/11
- Python 3.10+
- صلاحيات مسؤول (للتحكم في الخدمات)

## التثبيت السريع

1. ثبّت الحزم:

```bash
pip install -r requirements.txt
```

2. شغّل مرة واحدة كمسؤول:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

أو شغّل مباشرة:

```bat
Start.bat
```

## الاستخدام

- **كليك يسار** على أيقونة الـ Tray → واجهة التحكم
- **كليك يمين** → قائمة سريعة
- تشغيل / إيقاف لكل نسخة MySQL
- منع التشغيل التلقائي لخدمات ويندوز

## إزالة التشغيل مع ويندوز

```powershell
powershell -ExecutionPolicy Bypass -File .\Uninstall-Startup.ps1
```

## الترخيص

© فاتوس للبرمجيات — vatoce.com  
للاستخدام الخاص/التجاري حسب سياسة فاتوس.
