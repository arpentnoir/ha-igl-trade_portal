# Generated by Django 2.2.10 on 2020-08-26 07:37

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0029_document_extra_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='raw_certificate_data',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text="The data according the UNCoOSpec, most of it we don't parse; usually created through the API"),
        ),
    ]