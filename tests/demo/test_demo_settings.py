from demo_settings import Settings, compose_hint, missing_services


def test_defaults_point_at_the_lab_compose_ports():
    settings = Settings.from_environ({})

    assert settings.database_url.endswith("127.0.0.1:55432/warehouse_lab")
    assert settings.endpoints() == {
        "postgres": ("127.0.0.1", 55432),
        "rabbitmq": ("127.0.0.1", 55672),
        "valkey": ("127.0.0.1", 56379),
        "dynamodb-local": ("127.0.0.1", 58000),
        "loki": ("127.0.0.1", 53100),
        "alloy": ("127.0.0.1", 52345),
    }


def test_the_apps_own_environment_variables_override_the_defaults():
    settings = Settings.from_environ({"LAB_VALKEY_URL": "valkey://127.0.0.1:6000/0"})

    assert settings.endpoints()["valkey"] == ("127.0.0.1", 6000)


def test_missing_services_are_the_ones_nothing_listens_on():
    down = {"valkey", "loki"}
    probe = lambda host, port: {56379: "valkey", 53100: "loki"}.get(port) not in down  # noqa: E731

    assert missing_services(Settings.from_environ({}), probe) == ["valkey", "loki"]


def test_the_hint_is_the_exact_compose_command_for_the_lab_project():
    assert compose_hint(["valkey", "loki"]) == (
        "docker compose -p warehouse-fulfillment-lab up -d --wait valkey loki")
    assert compose_hint([]) == ""
