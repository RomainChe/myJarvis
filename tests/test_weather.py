"""weather_now : mesures complètes, signaux calculés, bornes, échec propre, lieu absent."""
import unittest
from unittest import mock

from jarvis.core import dashboard as d
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.home import weather as w


def fetch(body: str):
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = body.encode()
    with mock.patch("urllib.request.urlopen", return_value=resp):
        return d.fetch_weather(50.6, 3.0)


class FetchWeather(unittest.TestCase):
    def test_mesures_et_signaux(self):
        out = fetch('{"current": {"temperature_2m": 8.2, "apparent_temperature": 5, "weather_code": 95, "wind_speed_10m": 40,'
                    '"wind_gusts_10m": 75, "precipitation": 5, "relative_humidity_2m": 90},'
                    '"daily": {"weather_code": [95], "temperature_2m_max": [11], "temperature_2m_min": [-1],'
                    '"precipitation_probability_max": [80]}}')
        self.assertEqual((out["sky"], out["gust_kmh"], out["rain_chance"], out["min_c"]), ("Orage", 75.0, 80.0, -1.0))
        self.assertEqual(out["alerts"], ["orage", "vent fort", "forte pluie", "gel"])

    def test_champs_absents_ou_fous_donnent_none(self):
        out = fetch('{"current": {"temperature_2m": 20, "weather_code": 0, "wind_gusts_10m": 99999}}')
        self.assertEqual((out["sky"], out["gust_kmh"], out["min_c"], out["alerts"]), ("Dégagé", None, None, []))


class Tool(unittest.TestCase):
    def setUp(self):
        w._cache = None

    def test_niveau_n0_et_phrase(self):
        self.assertEqual(REGISTRY["weather_now"].level, Level.N0)
        data = {"temp_c": 14.0, "sky": "Pluie", "feels_c": 12.0, "wind_kmh": 25.0, "gust_kmh": 45.0, "rain_mm": 0.2,
                "humidity": 80.0, "min_c": 9.0, "max_c": 15.0, "rain_chance": 60.0, "alerts": ["vent fort"]}
        with mock.patch.object(d, "load_config", return_value={"city": "X", "lat": 1, "lon": 1}), \
                mock.patch.object(d, "fetch_weather", return_value=data) as f:
            text = w.weather_now()
            w.weather_now()
        self.assertEqual(f.call_count, 1)  # cache 15 min
        for part in ("14.0 °C", "pluie", "rafales 45.0", "60 % de risque", "vent fort", "pas la vigilance officielle"):
            self.assertIn(part, text)

    def test_lieu_absent(self):
        with mock.patch.object(d, "load_config", return_value=None):
            with self.assertRaisesRegex(ValueError, "non configuré"):
                w.weather_now()

    def test_echec_reseau_sans_detail(self):
        with mock.patch.object(d, "load_config", return_value={"city": "X", "lat": 1, "lon": 1}), \
                mock.patch.object(d, "fetch_weather", side_effect=OSError("http://api/?latitude=50.6")):
            with self.assertRaises(ValueError) as cm:
                w.weather_now()
        self.assertEqual(str(cm.exception), "météo indisponible")


if __name__ == "__main__":
    unittest.main()
