from django.core.management.base import BaseCommand, CommandError

from study.models import StudyCourse
from study.services import StudyIngestionService


class Command(BaseCommand):
    help = "Ingest a directory of study materials into markdown/theory artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--course-id", required=True, help="Study course UUID")
        parser.add_argument("--directory", required=True, help="Folder containing PDFs/images")
        parser.add_argument("--max-pages", type=int, default=None, help="Optional per-file page limit")
        parser.add_argument(
            "--no-recursive",
            action="store_true",
            help="Only ingest files directly under the given directory",
        )

    def handle(self, *args, **options):
        try:
            course = StudyCourse.objects.get(id=options["course_id"])
        except StudyCourse.DoesNotExist as exc:
            raise CommandError(f"Study course not found: {options['course_id']}") from exc

        result = StudyIngestionService.ingest_directory(
            course=course,
            directory=options["directory"],
            recursive=not options["no_recursive"],
            max_pages=options["max_pages"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Created {result['created']} / processed {result['processed']} / failed {result['failed']} / skipped {result['skipped']}"
        ))
