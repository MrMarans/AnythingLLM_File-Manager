import os

from django_q.models import Schedule


def setup_schedules():
    # Lösche eventuell vorhandene Schedules mit dem gleichen Namen
    Schedule.objects.filter(name="check_files_schedule").delete()

    # Get cron schedule from environment variable or use default (every minute)
    cron_schedule = os.environ.get("CHECK_FILES_CRON", "*/1 * * * *")

    # Erstelle einen neuen Schedule
    Schedule.objects.create(
        name="check_files_schedule",
        func="check_for_files.tasks.check_all_servers",
        schedule_type=Schedule.CRON,
        cron=cron_schedule,  # Use environment variable
        repeats=-1,  # Unendlich wiederholen
    )
