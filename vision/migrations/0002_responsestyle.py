# Generated by Django 5.0.7 on 2024-08-10 21:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ResponseStyle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('prompt', models.TextField()),
            ],
        ),
    ]