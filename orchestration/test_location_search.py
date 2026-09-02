from unittest.mock import Mock,patch
from django.core.cache import cache
from django.test import RequestFactory,TestCase
from orchestration.services import LocationSearchService
from orchestration.views import search_locations_for_note

class LocationSearchTests(TestCase):
    def setUp(self): cache.clear(); LocationSearchService._last_request_at=0
    @patch("httpx.get")
    def test_search_normalizes_results_identifies_client_and_caches(self,get):
        response=Mock();response.raise_for_status.return_value=None;response.json.return_value=[{"display_name":"Nicosia, Cyprus","name":"Nicosia","lat":"35.1856","lon":"33.3823","category":"place","type":"city","importance":0.8}];get.return_value=response
        first=LocationSearchService.search("Nicosia");second=LocationSearchService.search("Nicosia")
        self.assertEqual(first,second);self.assertEqual(first[0]["latitude"],35.1856);self.assertEqual(get.call_count,1)
        self.assertIn("CorvAI",get.call_args.kwargs["headers"]["User-Agent"])
    @patch("orchestration.services.LocationSearchService.search",return_value=[{"name":"Home","display_name":"Home address","latitude":1,"longitude":2}])
    def test_api_proxy(self,_search):
        result=search_locations_for_note(RequestFactory().get("/api/orchestration/knowledge/location-search"),"home")
        self.assertEqual(result["results"][0]["longitude"],2);self.assertIn("OpenStreetMap",result["attribution"])
