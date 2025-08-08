# Network Device Parser API

A FastAPI-based backend service for parsing network device configurations and outputs using TextFSM templates. The service provides JWT authentication, PostgreSQL database storage, and comprehensive parsing capabilities for multiple network device platforms.

## Features

- **JWT Authentication**: Secure user registration, login, and logout
- **Multi-Platform Support**: Cisco IOS, Cisco NX-OS, Aruba AOS-CX, Huawei VRP, Huawei YunShan
- **TextFSM Parsing**: Automated parsing using NTC templates
- **PostgreSQL Storage**: Persistent storage of parsed results
- **RESTful API**: Comprehensive REST endpoints for all operations
- **File Upload**: Support for .txt and .log files
- **Data Analysis**: CPU, memory, inventory, and interface analysis
- **Export Functionality**: Download parsed results as JSON

## Supported Platforms

| Platform | Commands Supported |
|----------|-------------------|
| Cisco IOS | show version, show inventory, show interfaces, show processes memory sorted, show processes cpu history |
| Cisco NX-OS | show version, show inventory, show interface, show system resources |
| Aruba AOS-CX | show system, show inventory, show interface |
| Huawei VRP | display version, display interface, display cpu-usage, display memory usage, display device |
| Huawei YunShan | display version, display interface, display cpu-usage, display memory usage, display device |

## Installation

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- pip

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd network-parser-api
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   
   Copy `.env.example` to `.env` and update the values:
   ```bash
   cp .env .env.local
   ```
   
   Update the following variables in `.env`:
   ```env
   DATABASE_URL=postgresql://username:password@localhost:5432/parser_db
   SECRET_KEY=your-super-secret-key-change-this-in-production
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   DEBUG=True
   UPLOAD_DIR=uploads
   ```

5. **Setup PostgreSQL database**
   ```sql
   CREATE DATABASE parser_db;
   CREATE USER parser_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE parser_db TO parser_user;
   ```

6. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

7. **Start the application**
   ```bash
   python -m app.main
   # or
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## API Documentation

Once the application is running, you can access:

- **Interactive API Documentation**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Login user and get JWT token |
| GET | `/auth/me` | Get current user info |
| POST | `/auth/logout` | Logout user |

### Parser Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/parser/upload` | Upload and parse device files |
| GET | `/parser/results` | Get all parse results |
| GET | `/parser/results/{id}` | Get specific parse result |
| DELETE | `/parser/results/{id}` | Delete parse result |
| GET | `/parser/summary` | Get device summary |
| GET | `/parser/cpu-memory` | Get CPU/Memory usage |
| GET | `/parser/inventory` | Get device inventory |
| GET | `/parser/interfaces` | Get interface information |
| GET | `/parser/download/{id}` | Download parsed JSON |

## Usage Examples

### 1. Register a User

```bash
curl -X POST "http://localhost:8000/auth/register" \
     -H "Content-Type: application/json" \
     -d '{
       "username": "testuser",
       "password": "SecurePass123!"
     }'
```

### 2. Login

```bash
curl -X POST "http://localhost:8000/auth/login" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=testuser&password=SecurePass123!"
```

### 3. Upload Files

```bash
curl -X POST "http://localhost:8000/parser/upload" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     -F "files=@device_config.txt"
```

### 4. Get Summary

```bash
curl -X GET "http://localhost:8000/parser/summary" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## Password Requirements

Passwords must meet the following criteria:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character (!@#$%^&*(),.?":{}|<>)

## File Requirements

- Supported file extensions: `.txt`, `.log`
- Files should contain network device command outputs
- Platform detection is automatic based on content

## Project Structure

```
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database connection
│   ├── models/              # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   └── parse_result.py
│   ├── schemas/             # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── user.py
│   │   └── parser.py
│   ├── routers/             # API routes
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   └── parser.py
│   └── utils/               # Utility functions
│       ├── __init__.py
│       ├── auth.py
│       └── parser.py
├── templates/               # TextFSM templates
├── alembic/                 # Database migrations
├── uploads/                 # File upload directory
├── requirements.txt
├── .env                     # Environment variables
├── alembic.ini             # Alembic configuration
└── README.md
```

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

### Adding New Platform Support

1. Add platform patterns to `app/utils/parser.py`
2. Add TextFSM template mappings
3. Create parsing functions for platform-specific data
4. Add templates to the `templates/` directory

## Production Deployment

### Environment Variables

For production, ensure you set:

```env
DEBUG=False
SECRET_KEY=your-production-secret-key
DATABASE_URL=postgresql://user:pass@prod-db:5432/parser_db
```

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Security Considerations

- Change the default `SECRET_KEY` in production
- Use environment variables for sensitive data
- Configure CORS properly for your frontend domain
- Use HTTPS in production
- Implement rate limiting
- Regular security updates

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the API documentation at `/docs`
- Review the logs for debugging information

## Changelog

### v1.0.0
- Initial release
- JWT authentication
- Multi-platform parsing support
- PostgreSQL integration
- RESTful API endpoints
- File upload and parsing
- Data analysis features