# Deploying FaceVault: Backend on Render + Frontend on Netlify

This guide walks you through deploying **FaceVault** with a split architecture:
- **Backend API on Render.com** (Python Flask + OpenCV Deep Learning AI + SQLite)
- **Frontend on Netlify** (High-speed Global CDN + PWA Mobile Installation + Audio)

---

## Part 1: Deploy Backend on Render.com

### Step 1: Push Project to GitHub
1. Create a repository on [GitHub.com](https://github.com) (e.g. `facevault-backend`).
2. In your terminal / command prompt, run:
   ```bash
   git init
   git add .
   git commit -m "FaceVault Biometric Backend"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/facevault-backend.git
   git push -u origin main
   ```

### Step 2: Create Web Service on Render
1. Go to [Render.com](https://render.com) and sign in.
2. Click **New +** &rarr; **Web Service**.
3. Connect your GitHub repository.
4. Fill in the details:
   - **Name:** `facevault-backend` *(or any unique name you like)*
   - **Region:** Closest to you (e.g., Singapore or Frankfurt)
   - **Environment:** `Docker` *(Render will automatically detect `Dockerfile`)*
   - **Plan:** Free
5. Click **Create Web Service**.
6. Wait 2–3 minutes for the build to finish. Once live, Render gives you your public backend URL:
   > Example: `https://facevault-backend.onrender.com`
7. Verify it's working by opening:
   > `https://facevault-backend.onrender.com/api/health`  
   *(Should return: `{"status": "healthy"}`)*

---

## Part 2: Deploy Frontend on Netlify

All frontend assets are pre-packaged in the [`netlify_frontend/`](./netlify_frontend/) folder.

### Step 1: Update API URL in Netlify Config
Open [`netlify_frontend/_redirects`](./netlify_frontend/_redirects) and [`netlify_frontend/netlify.toml`](./netlify_frontend/netlify.toml).  
Replace `YOUR-RENDER-SERVICE-NAME` with your actual Render URL from Part 1.

For example, in `netlify_frontend/_redirects`:
```
/api/*  https://facevault-backend.onrender.com/api/:splat  200!
/*      /index.html                                        200
```

### Step 2: Deploy to Netlify (2 Easy Ways)

#### Option A: Drag & Drop (Fastest — 10 Seconds)
1. Go to [app.netlify.com/drop](https://app.netlify.com/drop) and sign in.
2. Drag and drop the `netlify_frontend` folder from your desktop into the Netlify browser window.
3. Netlify will immediately deploy your site and provide a live URL:
   > Example: `https://facevault-biometrics.netlify.app`

#### Option B: GitHub Integration
1. Push the `netlify_frontend` folder to GitHub.
2. In Netlify, click **Add new site** &rarr; **Import an existing project**.
3. Select your repository. Set **Base directory** to `netlify_frontend` and **Publish directory** to `.`.
4. Click **Deploy Site**.

---

## Why this Architecture is Recommended

1. **Zero CORS Issues:** Netlify's `_redirects` proxy routes `/api/*` directly to Render behind the scenes, eliminating browser cross-origin blocks.
2. **Native Mobile Camera Support:** Both Netlify and Render provide automatic trusted HTTPS certificates, satisfying iOS Safari and Android Chrome security requirements for webcam access.
3. **PWA Mobile App Install:** Visitors opening your Netlify link on iPhone or Android can tap **"Install App"** to add FaceVault to their phone home screen.
