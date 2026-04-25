# TaskFlow Pro

[![CI/CD](https://github.com/bhogarinc/sdlc-master-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/bhogarinc/sdlc-master-pipeline/actions)
[![Coverage](https://codecov.io/gh/bhogarinc/sdlc-master-pipeline/branch/main/graph/badge.svg)](https://codecov.io/gh/bhogarinc/sdlc-master-pipeline)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An online task management application with team collaboration, real-time notifications, and comprehensive CI/CD pipeline.

## 🚀 Features

- **User Authentication**: Secure registration, login, password reset with JWT tokens
- **Task Management**: Full CRUD operations with priority levels, due dates, and status tracking
- **Team Collaboration**: Invite members, assign tasks, shared project boards
- **Real-time Notifications**: WebSocket-powered live updates for task changes
- **RESTful API**: FastAPI backend with auto-generated OpenAPI documentation

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React SPA     │────▶│  FastAPI API    │────▶│   PostgreSQL    │
│   (Frontend)    │◄────│   (Backend)     │◄────│   (Database)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  Redis Cache    │
                        └─────────────────┘
```

## 📁 Project Structure

```
sdlc-master-pipeline/
├── src/                          # Backend source code
│   ├── config/                   # Configuration management
│   ├── api/                      # API layer
│   │   ├── routes/              # API endpoints
│   │   ├── middleware/          # Auth, logging, error handling
│   │   └── schemas/             # Pydantic models
│   ├── services/                # Business logic layer
│   ├── models/                  # SQLAlchemy ORM models
│   ├── repositories/            # Data access layer
│   └── utils/                   # Utilities and helpers
├── frontend/                     # React frontend
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── store/
│   └── package.json
├── tests/                        # Test suites
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── migrations/                   # Alembic database migrations
├── docs/                         # Documentation
├── .github/workflows/            # CI/CD pipelines
├── docker-compose.yml
└── Makefile
```

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| Frontend | React 18, TypeScript, TailwindCSS |
| Database | PostgreSQL 15, Redis |
| Auth | JWT, OAuth2 |
| Real-time | WebSocket, Socket.io |
| Testing | pytest, Jest, Playwright |
| CI/CD | GitHub Actions |
| Deployment | Docker, Kubernetes |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL 15

### Backend Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run migrations
alembic upgrade head

# Start development server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Docker Setup

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## 🧪 Testing

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run specific test suite
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/
```

## 📖 API Documentation

When running locally:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch from `develop`: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests: `make test`
5. Commit with conventional commits: `git commit -m "feat: add new feature"`
6. Push to your fork: `git push origin feature/your-feature`
7. Create a Pull Request to `develop`

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code |
| `develop` | Integration branch for features |
| `feature/*` | New features |
| `bugfix/*` | Bug fixes |
| `hotfix/*` | Critical production fixes |
| `release/*` | Release preparation |

### Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting)
- `refactor:` Code refactoring
- `test:` Test additions/changes
- `chore:` Build/tooling changes

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👥 Team

- **Staff Engineer**: Architecture & DevOps
- **Backend Engineers**: API & Services
- **Frontend Engineers**: UI/UX
- **QA Engineers**: Testing & Quality

## 📞 Support

For support, email support@bhogarinc.com or create an issue in this repository.

---

Built with ❤️ by the bhogarinc team