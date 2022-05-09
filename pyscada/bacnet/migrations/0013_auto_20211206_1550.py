# Generated by Django 2.2.8 on 2021-12-06 15:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bacnet', '0012_auto_20211206_1335'),
    ]

    operations = [
        migrations.AddField(
            model_name='bacnetdevice',
            name='remote_devices_variables',
            field=models.CharField(default='', help_text='After creating a remote device, refresh the page until you see the result', max_length=1000),
        ),
        migrations.AlterField(
            model_name='bacnetdevice',
            name='remote_devices_discovered',
            field=models.CharField(default='', help_text='After creating a local device, refresh the page until you see the result', max_length=300),
        ),
    ]
