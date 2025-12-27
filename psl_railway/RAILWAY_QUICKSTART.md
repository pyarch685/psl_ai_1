# Railway Quick Start Guide

Quick reference for deploying to Railway.

## 1. Generate Secret Key

```bash
cd psl_railway
python scripts/generate_secrets.py
```

Copy the generated JWT_SECRET_KEY.

## 2. Set Up Railway Services

### Backend Service
1. Create new service from GitHub repo
2. Root directory: `/` (root of repository)
3. Set environment variables:
   ```
   ENVIRONMENT=production
   JWT_SECRET_KEY=<generated-key>
   CORS_ORIGINS=https://your-frontend-domain.com
   ```

### PostgreSQL Database
1. Add "PostgreSQL" service
2. Railway automatically sets `DATABASE_URL`

### Frontend Service
1. Create new service from same GitHub repo
2. Root directory: `web/vuvuzela-vibes-predictor`
3. Set environment variables:
   ```
   VITE_API_URL=https://your-backend-domain.up.railway.app
   ```

## 3. Initialize Database

```bash
railway run python db/create_schema.py
```

## 4. Set Custom Domains (Optional)

1. Backend: Settings → Networking → Add Custom Domain
2. Frontend: Settings → Networking → Add Custom Domain
3. Update `CORS_ORIGINS` and `VITE_API_URL` with custom domains

## 5. Verify Deployment

- Backend health: `https://your-backend-domain/health`
- Frontend: `https://your-frontend-domain`
- Check logs in Railway dashboard

For detailed instructions, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

