import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from orchestration.models import KnowledgeEntity, UserNote
from orchestration.registry import FunctionRegistry
from orchestration.services import KnowledgeBaseService, UserInfoService
from orchestration.views import create_knowledge_entity, delete_knowledge_entity, list_knowledge_tags, list_knowledge_type, search_knowledge, update_knowledge_entity


class StructuredKnowledgeServiceTests(TestCase):
    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_location_crud_coordinates_description_and_tags(self, _embed):
        item=KnowledgeBaseService.create("location",name="Home",description="The quiet flat",data={"latitude":35.1,"longitude":33.2,"door_code_hint":"blue"},tags=["personal","home"])
        self.assertEqual(item.data["latitude"],35.1); self.assertEqual(item.tags,["personal","home"])
        updated=KnowledgeBaseService.update(item.id,entity_type="location",description="The very quiet flat",data={"latitude":35.2})
        self.assertEqual(updated.data["longitude"],33.2); self.assertEqual(updated.data["latitude"],35.2)
        self.assertEqual(KnowledgeBaseService.get(item.id).description,"The very quiet flat")
        KnowledgeBaseService.delete(item.id,entity_type="location")
        with self.assertRaisesMessage(ValueError,"not found"): KnowledgeBaseService.get(item.id)

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_person_crud_relationship_facts_and_tags(self, _embed):
        item=KnowledgeBaseService.create("person",name="Maya",description="Met at university",data={"relationship":"friend","facts":["Likes jazz","Has a dog"]},tags=["friends"])
        payload=KnowledgeBaseService.payload(item)
        self.assertEqual(payload["data"]["relationship"],"friend"); self.assertEqual(payload["data"]["facts"],["Likes jazz","Has a dog"])
        updated=KnowledgeBaseService.update(item.id,entity_type="person",data={"facts":["Likes jazz","Moved home"]})
        self.assertEqual(updated.data["relationship"],"friend"); self.assertEqual(len(updated.data["facts"]),2)

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_general_search_unifies_notes_entities_tags_and_type_preference(self, _embed):
        UserInfoService.add_note(content="Home insurance renewal",tags=["home"])
        KnowledgeBaseService.create("location",name="Home",description="Main home",data={"latitude":1,"longitude":2},tags=["home"])
        KnowledgeBaseService.create("person",name="Home contractor",description="Repairs at home",data={"relationship":"contractor","facts":[]},tags=["home"])
        result=KnowledgeBaseService.search("home",tags=["home"],limit=10)
        self.assertEqual(result["preferred_types"],["location"])
        self.assertEqual([row["knowledge_type"] for row in result["results"]],["location","note","person"])

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_per_type_search_does_not_cross_types(self, _embed):
        KnowledgeBaseService.create("location",name="Harbour office",description="Work base",data={"latitude":1,"longitude":2})
        KnowledgeBaseService.create("person",name="Office manager",data={"relationship":"colleague","facts":[]})
        result=KnowledgeBaseService.list_type("location",query="office")
        self.assertEqual(len(result),1); self.assertEqual(result[0]["knowledge_type"],"location")

    def test_location_validation_rejects_bad_coordinates(self):
        with self.assertRaisesMessage(ValueError,"out of range"): KnowledgeBaseService.create("location",name="Mars",data={"latitude":100,"longitude":2})


class StructuredKnowledgeApiTests(TestCase):
    def setUp(self): self.factory=RequestFactory()
    def request(self,method,payload=None): return getattr(self.factory,method)("/api/orchestration/knowledge",data=json.dumps(payload or {}),content_type="application/json")

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_typed_api_crud_and_unified_tag_discovery(self,_embed):
        location=create_knowledge_entity(self.request("post",{"name":"Cabin","latitude":60.1,"longitude":24.9,"description":"Winter place","tags":["travel"]}),"location")
        person=create_knowledge_entity(self.request("post",{"name":"Niko","relationship":"friend","facts":["Skis"],"tags":["travel"]}),"person")
        listed=list_knowledge_type(self.factory.get("/api/orchestration/knowledge/person"),"person")
        updated=update_knowledge_entity(self.request("patch",{"facts":["Skis","Climbs"]}),"person",person["id"])
        tags=list_knowledge_tags(self.factory.get("/api/orchestration/knowledge/tags"))
        deleted=delete_knowledge_entity(self.request("delete"),"location",location["id"])
        self.assertEqual(len(listed["entities"]),1); self.assertEqual(updated["data"]["facts"],["Skis","Climbs"])
        self.assertEqual(tags["tags"],["travel"]); self.assertTrue(deleted["deleted"])

    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_general_search_api(self,_embed):
        KnowledgeBaseService.create("location",name="Home",data={"latitude":1,"longitude":2})
        result=search_knowledge(self.factory.get("/api/orchestration/knowledge/search"),query="home")
        self.assertEqual(result["preferred_types"],["location"]); self.assertEqual(result["results"][0]["name"],"Home")


class StructuredKnowledgeActionTests(TestCase):
    @patch("orchestration.services.UserInfoService._embed_text", return_value=None)
    def test_registered_actions_cover_crud_lists_and_general_search(self,_embed):
        import orchestration.tools.user_info  # noqa: F401
        create_location=FunctionRegistry.resolve_callable("user_info.create_location")
        update_location=FunctionRegistry.resolve_callable("user_info.update_location")
        list_locations=FunctionRegistry.resolve_callable("user_info.list_locations")
        delete_location=FunctionRegistry.resolve_callable("user_info.delete_location")
        create_person=FunctionRegistry.resolve_callable("user_info.create_person")
        search_all=FunctionRegistry.resolve_callable("user_info.search_knowledge")
        location=create_location("Home",1,2,tags=["personal"])
        update_location(location["id"],description="Main address")
        create_person("Ari",relationship="friend",facts=["Visits home"],tags=["personal"])
        self.assertEqual(len(list_locations(query="home")["locations"]),1)
        self.assertEqual(search_all("home")["results"][0]["knowledge_type"],"location")
        self.assertTrue(delete_location(location["id"])["deleted"])

    def test_persisted_module_guidance_preserves_plain_notes_and_explains_search(self):
        from orchestration.models import ToolFunction,ToolModule
        module=ToolModule.objects.get(slug="user_info")
        self.assertIn("plain user_info.add_note",module.caller_instructions)
        self.assertIn("search_knowledge",module.caller_instructions)
        self.assertEqual(ToolFunction.objects.filter(manifest_id__in=["user_info.create_location","user_info.create_person","user_info.search_knowledge"]).count(),3)
