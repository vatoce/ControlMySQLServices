# Control MySQL Services

**English** · **العربية** below

A Windows System Tray tool to start/stop MySQL instances — Windows Services and portable installs (Laragon / XAMPP / standalone `mysqld`).

**Vatoce Software — [vatoce.com](https://vatoce.com)**  
**فاتوس للبرمجيات — [vatoce.com](https://vatoce.com)**

Repository: [github.com/vatoceit-cloud/ControlMySQLServices](https://github.com/vatoceit-cloud/ControlMySQLServices)

---

## English

### Requirements

- Windows 10 / 11
- Python 3.10+
- Administrator privileges (to control Windows services)

### Quick install

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run once as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

Or launch directly:

```bat
Start.bat
```

### Usage

- **Left-click** the tray icon → control panel
- **Right-click** → quick menu
- Start / stop each MySQL instance
- Set Windows MySQL services to Manual (no auto-start)
- Optional: start this tool with Windows

MySQL services are **not** started automatically by this tool — only when you request it.

### Uninstall startup

```powershell
powershell -ExecutionPolicy Bypass -File .\Uninstall-Startup.ps1
```

### Features

- Discovers Windows MySQL / MariaDB services
- Discovers Laragon, XAMPP, WAMP and other portable installs
- Detects running standalone `mysqld` / `mariadbd` processes
- Compact modern UI with port badges and live status refresh

### License / Credits

© Vatoce Software — [vatoce.com](https://vatoce.com)  
Private/commercial use per Vatoce policy.

---

## العربية

### المتطلبات

- Windows 10 / 11
- Python 3.10+
- صلاحيات مسؤول (للتحكم في خدمات ويندوز)

### التثبيت السريع

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

### الاستخدام

- **كليك يسار** على أيقونة الـ Tray → واجهة التحكم
- **كليك يمين** → قائمة سريعة
- تشغيل / إيقاف لكل نسخة MySQL
- ضبط خدمات ويندوز على Manual (بدون تشغيل تلقائي)
- اختياري: تشغيل الأداة مع ويندوز

الأداة **لا تشغّل** MySQL من نفسها — إلا بطلب منك.

### إزالة التشغيل مع ويندوز

```powershell
powershell -ExecutionPolicy Bypass -File .\Uninstall-Startup.ps1
```

### المميزات

- اكتشاف خدمات MySQL / MariaDB في ويندوز
- اكتشاف Laragon و XAMPP و WAMP والنسخ المحمولة
- اكتشاف عمليات `mysqld` / `mariadbd` المستقلة الشغالة
- واجهة حديثة مضغوطة مع رقم البورت وتحديث تلقائي للحالة

### الترخيص / الحقوق

© فاتوس للبرمجيات — [vatoce.com](https://vatoce.com)  
للاستخدام الخاص/التجاري حسب سياسة فاتوس.
