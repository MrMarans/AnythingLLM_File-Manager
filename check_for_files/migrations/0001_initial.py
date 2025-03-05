# Generated by Django 5.1.6 on 2025-03-05 14:52

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="created_workspaces",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="FileInfo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("filename", models.CharField(max_length=255)),
                ("absolute_path", models.CharField(max_length=1024)),
                ("main_folder", models.CharField(max_length=255)),
                ("file_size", models.PositiveIntegerField(help_text="Size in bytes")),
                ("created_at", models.DateTimeField()),
                ("modified_at", models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name="TaskError",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateTimeField(auto_now_add=True)),
                ("error", models.TextField(blank=True, null=True)),
                ("success", models.BooleanField(default=True)),
            ],
        ),
    ]
