# Generated manually (sandbox venv lacks face_recognition/dlib needed to run makemigrations)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0018_spoofingattempt_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='face_encodings',
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
