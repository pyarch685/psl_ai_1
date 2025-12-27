# Railway Deployment Guide

Complete guide for deploying the PSL Soccer Predictor application to Railway.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Railway Setup](#railway-setup)
3. [Backend Deployment](#backend-deployment)
4. [Frontend Deployment](#frontend-deployment)
5. [Database Setup](#database-setup)
6. [Environment Variables](#environment-variables)
7. [Custom Domains](#custom-domains)
8. [Monitoring & Maintenance](#monitoring--maintenance)
9. [Troubleshooting](#troubleshooting)

## Prerequisites

- Railway account (sign up at https://railway.app)
- GitHub repository with your code
- Custom domain (optional but recommended)

## Railway Setup

### 1. Create Railway Project

1. Log in to Railway
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Connect your GitHub account if needed
5. Select the repository containing this code

## Backend Deployment

### 1. Create Backend Service

1. In your Railway project, click "New" → "Service"
2. Select "GitHub Repo" and choose your repository
3. Railway will detect the Dockerfile and configure automatically

### 2. Configure Backend Environment Variables

Set these in Railway's environment variables (Settings → Variables):

**Required:**
- `ENVIRONMENT=production`
- `JWT_SECRET_KEY` - Generate using: `python scripts/generate_secrets.py`
- `CORS_ORIGINS` - Your frontend domain(s), comma-separated
  - Example: `https://yourdomain.com,https://www.yourdomain.com`

**Database (if using Railway PostgreSQL):**
- `DATABASE_URL` - Automatically set by Railway when you add PostgreSQL service
- OR set individually:
  - `DB_HOST`
  - `DB_PORT`
  - `DB_NAME`
  - `DB_USER`
  - `DB_PASSWORD`

**Optional:**
- `PORT=8000` - Railway sets this automatically
- `LOG_LEVEL=INFO` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `MODEL_STORAGE_PATH=/data/models` - Path for model storage (Railway volume)

### 3. Set Up Persistent Storage for Models

1. In your backend service, go to "Settings" → "Volumes"
2. Click "New Volume"
3. Set mount path: `/data/models`
4. This ensures ML models persist across deployments

### 4. Configure Health Checks

Railway will automatically use the `/health` endpoint for health checks.

## Frontend Deployment

### 1. Create Frontend Service

1. In your Railway project, click "New" → "Service"
2. Select "GitHub Repo" and choose your repository
3. Set root directory: `web/vuvuzela-vibes-predictor`
4. Railway will detect the Dockerfile and configure automatically

### 2. Configure Frontend Environment Variables

Set these in Railway's environment variables:

**Required:**
- `VITE_API_URL` - Your backend API URL
  - Example: `https://your-backend-service.up.railway.app`

**Optional:**
- `PORT=80` - Nginx runs on port 80

### 3. Build Configuration

The frontend uses a multi-stage Docker build:
- Stage 1: Builds the React/Vite application
- Stage 2: Serves with nginx

## Database Setup

### Option 1: Railway Managed PostgreSQL (Recommended)

1. In your Railway project, click "New" → "Database" → "PostgreSQL"
2. Railway automatically creates the database and sets `DATABASE_URL`
3. The backend will automatically connect using this URL

### Option 2: External PostgreSQL

1. Set individual database environment variables (see Backend section)
2. Ensure SSL/TLS is enabled for production connections

### Initialize Database Schema

After deployment, run database migrations:

1. Connect to your Railway PostgreSQL service
2. Use Railway's CLI or web console to execute:
   ```bash
   railway run python db/create_schema.py
   ```

Or import initial data:
```bash
railway run python db/import_csv.py
```

## Environment Variables

### Backend Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `ENVIRONMENT` | Yes | Environment type | `production` |
| `JWT_SECRET_KEY` | Yes | Secret for JWT tokens | Generated secret |
| `DATABASE_URL` | Yes* | PostgreSQL connection URL | Auto-set by Railway |
| `CORS_ORIGINS` | Yes | Allowed frontend origins | `https://yourdomain.com` |
| `PORT` | No | Server port | `8000` (auto-set) |
| `LOG_LEVEL` | No | Logging level | `INFO` |
| `MODEL_STORAGE_PATH` | No | Model storage path | `/data/models` |

*Either `DATABASE_URL` or individual `DB_*` variables required.

### Frontend Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `VITE_API_URL` | Yes | Backend API URL | `https://api.yourdomain.com` |

## Custom Domains

### Backend Domain

1. In backend service, go to "Settings" → "Networking"
2. Click "Generate Domain" or "Add Custom Domain"
3. For custom domain:
   - Add your domain (e.g., `api.yourdomain.com`)
   - Follow Railway's DNS configuration instructions
   - SSL/TLS is automatically provisioned

### Frontend Domain

1. In frontend service, go to "Settings" → "Networking"
2. Follow same process as backend
3. Update `VITE_API_URL` to point to your backend domain

### Update CORS

After setting custom domains, update `CORS_ORIGINS` in backend:
```
https://yourdomain.com,https://www.yourdomain.com
```

## Monitoring & Maintenance

### Logs

View logs in Railway dashboard:
- Go to service → "Deployments" → Select deployment → "View Logs"

### Health Checks

- Backend: `GET /health`
- Frontend: `GET /health`

Both return 200 OK when healthy.

### Database Backups

Railway PostgreSQL includes automatic backups. To manually backup:

1. Use Railway's database backup feature
2. Or export using `pg_dump`:
   ```bash
   railway connect postgres
   pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE > backup.sql
   ```

### Model Backups

Models are stored in Railway volumes. To backup:

1. Use Railway's volume backup feature
2. Or copy files using Railway CLI:
   ```bash
   railway run cp /data/models/latest.joblib ./backup.joblib
   ```

## Troubleshooting

### Backend Issues

**Problem:** Backend fails to start
- Check logs in Railway dashboard
- Verify all required environment variables are set
- Ensure `JWT_SECRET_KEY` is not the default value

**Problem:** Database connection fails
- Verify `DATABASE_URL` is set correctly
- Check PostgreSQL service is running
- Ensure SSL is enabled (automatic with Railway PostgreSQL)

**Problem:** CORS errors
- Verify `CORS_ORIGINS` includes your frontend domain
- Check frontend is using correct `VITE_API_URL`

### Frontend Issues

**Problem:** Frontend shows blank page
- Check browser console for errors
- Verify `VITE_API_URL` is set correctly
- Check nginx logs in Railway dashboard

**Problem:** API calls fail
- Verify backend is running and accessible
- Check CORS configuration in backend
- Verify frontend domain is in `CORS_ORIGINS`

### Database Issues

**Problem:** Schema creation fails
- Ensure database service is running
- Check connection credentials
- Verify user has CREATE TABLE permissions

**Problem:** Data import fails
- Check CSV file format
- Verify table schema matches data
- Check database logs for specific errors

## Security Checklist

- [ ] `JWT_SECRET_KEY` is set to a strong, random value
- [ ] `CORS_ORIGINS` is restricted to your frontend domain(s)
- [ ] Database uses SSL/TLS connections (automatic with Railway)
- [ ] All environment variables are set in Railway (not in code)
- [ ] API docs are disabled in production (`/docs` and `/redoc`)
- [ ] Security headers are enabled (automatic via middleware)
- [ ] Custom domains use SSL/TLS (automatic with Railway)
- [ ] Database backups are enabled
- [ ] Model storage is on persistent volumes

## Support

For Railway-specific issues, consult:
- Railway Documentation: https://docs.railway.app
- Railway Discord: https://discord.gg/railway

For application issues, check the application logs in Railway dashboard.

