# Google Sheets setup

The tool writes to your sheet as a **service account** - a robot Google user that only has access to the
spreadsheets you share with it. You do this once.

## 1. Create the service account

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create a project (or pick one).
2. **APIs & Services -> Library -> Google Sheets API -> Enable.**
3. **IAM & Admin -> Service Accounts -> Create service account.** Any name (e.g. `immersion-tracker`).
   It needs **no roles**.
4. Open the new service account -> **Keys -> Add key -> Create new key -> JSON.** A `.json` file downloads.
5. Save it as `credentials/service_account.json` inside this project (the folder is git-ignored).

> The key is a password. Never commit it, paste it into a chat or screenshot it. If it leaks, delete the key in
> the console and create a new one.

## 2. Share the sheet with it

Open the key file and copy the `client_email` value (`something@your-project.iam.gserviceaccount.com`).
In your spreadsheet click **Share**, paste that address and give it **Editor** access.

## 3. Tell the tool which spreadsheet

The id is the long part of the sheet's URL: `https://docs.google.com/spreadsheets/d/`**`<ID>`**`/edit`.

```bash
cp .env.example .env
# edit .env:   SPREADSHEET_ID=<ID>
```

## 4. Lay out the week tables

The tab named by `worksheet` in `config.toml` (default `חשיפה`) holds one table per week:

```
曜日 | Alice | Ben  | Chloe        <- header: marker in the corner, one column per student
日   |       |      |              <- seven rows, the weekday labels in order
月   |       |      |                 (Sunday first when week_starts_on = "sunday")
火   |       |      |
...
```

- Name each table `week 1`, `week 2`, ... (Google Sheets: **Insert -> Table**, then rename it). If the sheet
  has no named tables, the tool scans for the `曜日` marker instead and numbers the tables top to bottom.
- The header texts must match the sheet columns you pick during `--setup`.
- The tool also creates two tabs of its own: the **log** tab (`log_worksheet`) and the **chart data** tab
  (`charts.data_worksheet`). Don't type in them - they are rewritten on every run.

## 5. Try it

```bash
python main.py chat.txt --dry-run      # reads the sheet, writes nothing
```
