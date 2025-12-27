# PSL AI - Railway Production Deployment

This directory contains the production-ready configuration and files for deploying the PSL Soccer Predictor application to Railway.

## Quick Start

1. **Generate Secret Key**
   ```bash
   python scripts/generate_secrets.py
   ```

2. **Set Up Railway**
   - Create Railway account and project
   - Add PostgreSQL database service
   - Deploy backend service (uses Dockerfile in root)
   - Deploy frontend service (uses Dockerfile in web/vuvuzela-vibes-predictor)

3. **Configure Environment Variables**
   - Backend: See `.env.example` and `docs/DEPLOYMENT.md`
   - Frontend: Set `VITE_API_URL` to your backend URL

4. **Initialize Database**
   ```bash
   railway run python db/create_schema.py
   ```

For detailed instructions, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Directory Structure

```
psl_railway/
├── Dockerfile                 # Backend container definition
├── railway.json              # Railway backend configuration
├── .dockerignore             # Files to exclude from Docker build
├── .env.example              # Environment variables template
├── requirements.txt          # Python dependencies
├── main.py                   # Application entry point (production-ready)
├── app/                      # FastAPI application
├── core/                     # ML prediction logic
├── jobs/                     # Background jobs (scraper, scheduler)
├── db/                       # Database utilities
├── config/                   # Configuration modules
│   ├── settings.py          # Environment configuration
│   └── production.py        # Production-specific settings
├── scripts/                  # Utility scripts
│   ├── generate_secrets.py  # Generate secure secret keys
│   └── health_check.py      # Health check utility
├── web/
│   └── vuvuzela-vibes-predictor/
│       ├── Dockerfile       # Frontend container definition
│       ├── railway.json     # Railway frontend configuration
│       ├── nginx.conf       # Nginx configuration
│       └── .env.production  # Frontend environment template
└── docs/
    └── DEPLOYMENT.md        # Complete deployment guide
```

## Key Features

### Security
- Environment-based configuration
- CORS restricted to specific domains
- Security headers (HSTS, X-Frame-Options, CSP, etc.)
- SSL/TLS enforced for database connections
- JWT authentication with configurable expiration
- API documentation disabled in production

### Production Ready
- Multi-stage Docker builds for optimized images
- Health check endpoints
- Graceful shutdown handling
- Structured logging
- Connection pooling with retry logic
- Persistent storage for ML models

### Railway Optimized
- Automatic database URL detection
- Port configuration via Railway's PORT env var
- Volume mounts for model persistence
- Health checks for Railway monitoring
- Custom domain support

## Environment Variables

See `.env.example` for all required and optional environment variables.

**Critical Variables:**
- `JWT_SECRET_KEY` - Must be set to a strong random value
- `DATABASE_URL` - Automatically set by Railway PostgreSQL service
- `CORS_ORIGINS` - Must include your frontend domain(s)
- `VITE_API_URL` - Frontend needs backend API URL

## Deployment Checklist

Before deploying:

- [ ] Generate and set `JWT_SECRET_KEY`
- [ ] Set `CORS_ORIGINS` to your frontend domain
- [ ] Verify database connection (Railway sets `DATABASE_URL`)
- [ ] Set `VITE_API_URL` in frontend service
- [ ] Configure persistent volume for models (`/data/models`)
- [ ] Set custom domains (optional but recommended)
- [ ] Initialize database schema
- [ ] Train initial ML model (if needed)

## Support

For deployment issues, see:
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) - Complete deployment guide
- Railway Documentation: https://docs.railway.app

