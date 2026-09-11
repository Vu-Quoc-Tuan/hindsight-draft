from scripts.review_learning.train_ranker import sanitize_creation_command


def test_sanitize_creation_command_uri_credentials():
    cmd = [
        "scripts/review_learning/train_ranker.py",
        "--source", "postgres",
        "--database-url", "postgresql+asyncpg://admin:supersecret@10.0.0.1:5432/nocpro_db",
    ]
    sanitized = sanitize_creation_command(cmd)
    assert "supersecret" not in sanitized
    assert "admin" not in sanitized
    assert "postgresql+asyncpg://***:***@10.0.0.1:5432/nocpro_db" in sanitized


def test_sanitize_creation_command_query_params():
    cmd = [
        "scripts/review_learning/train_ranker.py",
        "--database-url", "postgres://cluster:5432/db?sslkey=/path/to/key.pem&password=my_query_password&token=secret_tok_123",
    ]
    sanitized = sanitize_creation_command(cmd)
    assert "my_query_password" not in sanitized
    assert "secret_tok_123" not in sanitized
    assert "password=***" in sanitized
    assert "token=***" in sanitized
    assert "sslkey=***" in sanitized


def test_sanitize_creation_command_flag_parameters():
    cmd = [
        "scripts/review_learning/train_ranker.py",
        "--signing-key", "my_super_private_signing_key_456",
        "--token", "jwt_header_secret_789",
    ]
    sanitized = sanitize_creation_command(cmd)
    assert "my_super_private_signing_key_456" not in sanitized
    assert "jwt_header_secret_789" not in sanitized
    assert "--signing-key ***" in sanitized
    assert "--token ***" in sanitized
