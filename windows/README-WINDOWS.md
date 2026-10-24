# Running Reel Library on Windows

## 1. Install Docker Desktop

1. Download and install **Docker Desktop for Windows**: https://www.docker.com/products/docker-desktop/
2. When it asks, keep **"Use WSL 2"** selected. Restart if Windows asks you to.
3. Open Docker Desktop and wait until the bottom-left corner says **Engine running**.

## 2. Give Docker enough memory

The analysis (speech model + Laya) needs about 6 GB. On the Mac it crashed at 8 GB because other
containers were sharing it. On Windows, Docker's memory is set by WSL:

1. Press `Win + R`, type `notepad %UserProfile%\.wslconfig`, press Enter, and create the file if asked.
2. Paste this (for a 16 GB PC; use about two-thirds of your RAM):

   ```
   [wsl2]
   memory=10GB
   swap=4GB
   ```

3. Save, then open **PowerShell** and run `wsl --shutdown`. Start Docker Desktop again.

## 3. Unzip and start

1. Download `reel-library-windows-<version>.zip` from the
   [latest release](https://github.com/ic3w4r/reel-library/releases/latest) and unzip it into `C:\`,
   so you get the folder `C:\reel-library`.
   (Avoid OneDrive folders: syncing can lock files during the build.)
2. Optional, to bring your existing library over from the Mac: put `instamcp-library.tgz` in
   `C:\reel-library` and double-click `windows\restore-library.bat` **before** step 3.
3. Double-click `windows\start.bat`. It downloads the ready-made app (1-2 GB the first time) and
   starts it. Your browser then opens **http://localhost:8090**.

**"ports are not available … Only one usage of each socket address"**: port 8090 is already used
on this PC (by another app, or reserved by Windows). Create a file named `.env` in `C:\reel-library`
containing one line, for example `INSTAMCP_PORT=8095`, and run `start.bat` again. The app is then at
http://localhost:8095.

**To update** to a newer release, just double-click `windows\start.bat` again: it downloads the
newest version and restarts the app. Your library, settings and models are kept.

To stop it: `docker compose stop` in `C:\reel-library`, or stop the `instamcp` container in Docker Desktop.
It starts again on its own when Docker Desktop starts.

## 4. Connect LM Studio

In the app: **Settings → AI engines → LM Studio**.

- **LM Studio on this same PC** (simplest, no LM Link needed): in LM Studio open **Local Model API**,
  turn the server on, and note the port. Set the Base URL to
  `http://host.docker.internal:<port>/v1` (for example `http://host.docker.internal:1234/v1`).
  **Do not use `localhost`**: inside Docker that points at the container, not at Windows.
- **LM Studio on another machine**: use LM Link as on the Mac, or that machine's LAN address,
  e.g. `http://192.168.1.50:1234/v1` (turn on "Serve on local network" in LM Studio there).

Click **Fetch models**, pick `qwen3-vl-8b-instruct`, **Save**, then **Test**.

If Windows Firewall asks about LM Studio or Docker, choose **Allow** on private networks.

## 5. Instagram login

If you restored a backup, the Instagram login came with it. Otherwise connect it again in
**Settings → Instagram login**.

## Notes

- **Run the library on one machine at a time.** The Mac and the PC each keep their own copy;
  reels analyzed on one won't show up on the other. Move it again with `backup-library.sh` on the
  Mac and `restore-library.bat` here.
- The backup file holds your API keys and Instagram login. Don't share it.
- The analysis queue now survives restarts: if the container is restarted mid-batch, it carries on
  with the remaining reels. A reel that crashes the server twice is marked failed with a note.
- If a batch keeps failing with "ran out of memory", raise `memory=` in `.wslconfig`, or in **Settings → Video
  analysis** set the speech model to `small` and turn off the automatic Laya signals.
