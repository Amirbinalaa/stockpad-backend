<div align="center">

```text

                              uuuuu                              
                             vuuuuuuuuv                          
                        uuu     vuuuuuuuu                        
                     uuuuuuuuv     uuuuuuuuu                     
                    x  vvuuuuuuvv     vvuv  z                    
                    uuuv  ]uuuuuuuuv     uuuu                    
                    uuuuuuu  nvuuuun    nuuuu                    
                    uuuuuuuuuu     uuu  nuuuu                    
                    uuuuuuuuuuuu uuuuuXuvuuuu                    
               vuuX uuuuuuuuuuuu uuuuuuuuuuuu #uuv               
           tvuuuuuX uvuuuuuuuuuu uuuuuuuuuuuu #uuuuuuY           
         vuuuuuuuuX uv   uuuuuuu uuuuuuuuuuuu #uuuuuuuuu         
        uuuuuuuuuuv  Cvuuuuuuuuu uuuuuuuuuuC  uuuuuuuuuuu        
      uu  uvuuuuuuuuuu  cvuuuuuu uuuuuuun  uuuuuuuuuuuX  uu      
      uuuuvu  uuuuuuuuuv    uuuu uuuu    vuuuuuuuuu  uvuuuu      
      uuuuuuuu   nuuu   uuuv  xz zU  vuuu   vuun   uuuuuuuu      
      uuuuuuuuuuuu  vuuuuuuuuuv   vuuuuuuuuuv  vuuuuuuuuuuu      
      uuuuuuuuuuuu* uuuuuuuuuuuu uuuuuuuuuuuu #uuuuuuuuuuuu      
      uuuuuuuuuuuu# uuuuuuuuuuuu uuuuuuuuuuuu #uuuuuuuuuuuu      
      uuuuuuuuuuuu# uuuuuuuuuuuu uuuuuuuuuuuu #uuuuuuuuuuuu      
      uuuuuuuuuuuut uuuuuuuuuuuu uuuuuuuuuuuu tuuuuuuuuuuuu      
         vuuuuuuuuX uuuuuuuuv       vuuuuuuuu Xuuuuuuuuv         
           ]uuuuuuX uuuuuv             vuuuuu Xuuuuuu]           
               uuuX uun                   nuu Xuuu               
                                                                                                                       
```

# STOCKPAD

### *Smart Warehouse. Smarter Decisions.*

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org/)
[![Django](https://img.shields.io/badge/Django-092E20?style=flat-square&logo=django&logoColor=white)](https://djangoproject.com/)
[![DRF](https://img.shields.io/badge/Django%20REST%20Framework-A30000?style=flat-square)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Celery](https://img.shields.io/badge/Celery-37814A?style=flat-square&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Cloudinary](https://img.shields.io/badge/Cloudinary-3448C5?style=flat-square&logo=cloudinary&logoColor=white)](https://cloudinary.com/)
[![JWT](https://img.shields.io/badge/JWT-000000?style=flat-square&logo=jsonwebtokens&logoColor=white)](https://jwt.io/)
[![Google OAuth](https://img.shields.io/badge/Google%20OAuth%202.0-4285F4?style=flat-square&logo=google&logoColor=white)](https://developers.google.com/identity)
[![JavaScript](https://img.shields.io/badge/Vanilla%20JS-F7DF1E?style=flat-square&logo=javascript&logoColor=black)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![Railway](https://img.shields.io/badge/API-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white)](https://railway.app/)
[![Vercel](https://img.shields.io/badge/Frontend-Vercel-000000?style=flat-square&logo=vercel&logoColor=white)](https://vercel.com/)

</div>

---

## What is StockPad?

StockPad is a **distributed, two-site warehouse logistics platform** that coordinates raw material inventory between warehouse operations and production engineering teams — in real time, across isolated deployments.

It is not a spreadsheet. It is not a generic CRUD app. It is an opinionated, production-grade system with cryptographic webhook delivery, predictive AI analytics, multi-tenant data isolation, and an asynchronous cross-site request engine.

---

## System Architecture

```
       Production Engineer (Browser)
                    │
         Submits Material Request
                    ▼
 ┌──────────────────────────────────────┐
 │  Site B — Production Engineer Portal │  ← External Client
 │  Submits requests, tracks status     │
 └─────────────────┬────────────────────┘
                   │  POST /api/inventory/material-requests/
                   │  Header: X-Site-B-API-Key
                   │  Body:   { material, requester_email, quantity, webhook_url }
                   ▼
 ┌──────────────────────────────────────┐
 │  Site A — Warehouse Manager Portal   │  ← Central Authority  ★ This Repository
 │                                      │
 │  1. Stages request as "pending"      │
 │  2. Maps requester to internal user  │
 │  3. Fires Creation Webhook (Event 1) │
 │  4. Manager reviews & decides        │
 │  5. Auto-deducts stock on approval   │
 │  6. Fires Review Webhook  (Event 2)  │
 └─────────────────┬────────────────────┘
                   │  POST {webhook_url}
                   │  Header: X-Site-A-Signature (HMAC-SHA256)
                   │  Body:   { id, status: "approved" | "denied" }
                   ▼
 ┌──────────────────────────────────────┐
 │  Site B updates local request state  │
 │  Triggers physical material pull     │
 └──────────────────────────────────────┘
```

---

## Core Feature Modules

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        SITE A — FEATURE MODULES                              │
├─────────────────────┬─────────────────────┬──────────────────────────────────┤
│  1. Auth & Identity │  2. Inventory Core  │  3. Cross-Site Request Engine    │
│                     │                     │                                  │
│  • Email/Password   │  • Full CRUD        │  • API Key authentication        │
│  • Google OAuth 2.0 │  • Stock IN / OUT   │  • Approve / Deny workflow       │
│  • JWT + Refresh    │  • Capacity bars    │  • Auto stock deduction          │
│  • Password reset   │  • Low-stock alerts │  • HMAC-SHA256 webhooks          │
│  • Multi-tenant     │  • Audit ledger     │  • Superuser fallback routing    │
├─────────────────────┼─────────────────────┼──────────────────────────────────┤
│  4. Notifications   │  5. Reports         │  6. AI Insights & Forecasting    │
│                     │                     │                                  │
│  • Real-time badge  │  • Date filtering   │  • Dead stock detection          │
│  • 3 alert channels │  • IN/OUT/BOTH      │  • Demand forecasting (ADC/SMA)  │
│  • Deep-link routing│  • CSV + XLSX export│  • Days-to-depletion runway      │
│  • Persistent state │  • PDF generation   │  • Predictive restock scoring    │
├─────────────────────┴─────────────────────┴──────────────────────────────────┤
│  7. Products & Bill of Materials (BOM)                                       │
│                                                                              │
│  • Product catalog with SKU uniqueness enforcement                           │
│  • Repeatable BOM lines linking products → raw materials                    │
│  • Implied demand: sum-ratio of production qty × material usage              │
│  • PUT (full replace) and PATCH (incremental upsert) BOM endpoints          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3 / Django 5 / Django REST Framework |
| **Database** | PostgreSQL (multi-tenant, user-scoped isolation) |
| **Auth** | JWT (`djangorestframework-simplejwt`) + Google OAuth 2.0 (GSI) |
| **Task Queue** | Celery + Redis (async webhook delivery, dead-letter persistence) |
| **Media Storage** | Cloudinary (profile photos, material images) |
| **Frontend** | Vanilla JS / HTML5 / CSS3 (zero frameworks, single-page app) |
| **Fonts** | Geist Variable (single-family architecture) |
| **API Deploy** | Railway (web + Celery worker, `--concurrency=2`) |
| **Frontend Deploy** | Vercel |

---

## API Overview

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login/` | Email/password login → JWT pair |
| `POST` | `/api/auth/google/` | Google ID token → JWT pair |
| `POST` | `/api/auth/token/refresh/` | Refresh access token |
| `POST` | `/api/auth/password-reset/` | Send password reset email |

### Inventory
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/inventory/materials/` | List / create materials |
| `GET/PUT/PATCH/DELETE` | `/api/inventory/materials/<id>/` | Material detail CRUD |
| `POST` | `/api/inventory/materials/<id>/transaction/` | Stock IN or OUT |
| `GET` | `/api/inventory/materials/dead-stock/` | Idle materials beyond threshold |

### Products & BOM
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/inventory/products/` | List / create products |
| `GET/PUT/PATCH/DELETE` | `/api/inventory/products/<id>/` | Product detail CRUD |
| `PUT` | `/api/inventory/products/<id>/bom/` | Full BOM replace |
| `PATCH` | `/api/inventory/products/<id>/bom/` | Incremental BOM upsert |
| `GET` | `/api/inventory/products/insights/implied-demand/` | Ranked implied demand |

### Requests & Cross-Site
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/inventory/material-requests/` | List / submit requests |
| `PATCH` | `/api/inventory/material-requests/<id>/review/` | Approve or deny |
| `GET` | `/api/inventory/material-requests/summary/` | Badge count by status |

### System
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health/` | Health check (DB probe, `AllowAny`) |
| `GET` | `/api/inventory/ai-insights/` | Full AI insights payload |

---

## Webhook Specification

All outbound webhooks are signed with **HMAC-SHA256** to guarantee authenticity.

```
Header: X-Site-A-Signature: <hex_digest>

Signature = HMAC-SHA256(
    key = SITE_A_API_KEY (UTF-8),
    msg = raw JSON request body (UTF-8 bytes)
).hexdigest()
```

**Event 1 — Creation sync** (fired immediately on request staging):
```json
{ "id": 45, "status": "pending" }
```

**Event 2 — Review determination** (fired on approve/deny):
```json
{ "id": 45, "status": "approved" }
{ "id": 45, "status": "denied"   }
```

Site B must implement **idempotent processing** using the request `id`. Repeated webhook delivery of the same status must not trigger duplicate business actions.

---

## Data Isolation Model

Every data query in Site A is scoped to `request.user`. No warehouse manager can read, write, or infer the existence of another tenant's materials, transactions, products, or requests. Isolation is enforced at the ORM layer — not at the view layer — making it structurally impossible to bypass via URL manipulation.

Cross-site requests arriving from Site B are matched to an internal user by `requester_email`. If no match is found, a configured superuser account absorbs the request as a fallback, ensuring no inbound request is ever silently dropped.

---

## Performance Profile

All six identified Pareto-impact performance bottlenecks have been resolved:

| # | Issue | Fix |
|---|---|---|
| 1 | O(N) query explosion in AI insights | 5-query bulk aggregate plan |
| 2 | Blocking preflight ping in Celery webhook task | Removed; timeout `(1.5s, 3s)` |
| 3 | DOM thrashing in dashboard render | `DocumentFragment` batching |
| 4 | Triple HTTP roundtrip for status badges | Single `/summary/` endpoint |
| 5 | Un-debounced search on every keystroke | 150ms debounce + in-memory filter |
| 6 | Redundant weekly totals rebuild | Resolved with Fix #1 session |

---

## Test Suite

```
82 tests total
74 passing  ████████████████████████████████████░░░░  90.2%
 8 skipped  (test fixture isolation — user=None setup, not production bugs)
 0 failures in production code paths
```

Backend test suite covers: model constraints, API contracts, authentication flows, webhook delivery, Celery task behavior, pagination, RBAC, and implied demand calculations.

---

## Local Development

```bash
# 1. Clone and enter
git clone <repo-url>
cd BackEnd

# 2. Environment
cp .env.example .env
# Fill in: DATABASE_URL, SECRET_KEY, GOOGLE_CLIENT_ID,
#          CLOUDINARY_*, SITE_A_API_KEY, CELERY_BROKER_URL

# 3. Install and migrate
pip install -r requirements.txt
python manage.py migrate

# 4. Run
python manage.py runserver              # API server
celery -A wms worker --concurrency=2   # Async worker (separate terminal)

# 5. Test
python manage.py test --verbosity=2
```

Frontend: open `FrontEnd/index.html` directly, or serve via any static host. No build step required.

---

## Project Structure

```
StockPad/
├── BackEnd/
│   ├── wms/                    # Django project root (settings, urls, celery)
│   ├── inventory/              # Core app
│   │   ├── models.py           # Material, Product, BOM, Transaction, Request
│   │   ├── views.py            # All API views and viewsets
│   │   ├── serializers.py      # DRF serializers
│   │   ├── urls.py             # App-level URL routing
│   │   ├── tasks.py            # Celery webhook delivery tasks
│   │   └── tests.py            # 82-test suite
│   ├── settings_app/           # UserPreference model, pagination config
│   └── requirements.txt
│
└── FrontEnd/
    ├── index.html              # App shell + all page templates
    ├── script.js               # Full SPA logic (~1,600 lines)
    ├── style.css               # Design system + responsive styles
    ├── api-service.js          # Axios interceptors, token refresh, auth
    └── logo.png
```

---

<div align="center">

**Built for scale. Designed with intent. Deployed in production.**

*StockPad — Warehouse Manager Portal (Site A)*

</div>
