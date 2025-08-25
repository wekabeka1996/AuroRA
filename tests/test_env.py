from core.env import load_env


def test_load_env_defaults():
    env = load_env(dotenv=False)
    assert env.EXCHANGE_ID == 'binanceusdm'
    assert isinstance(env.EXCHANGE_TESTNET, bool)
