# Generated by Django 2.2.8 on 2021-09-30 09:56

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pyscada', '0080_variableproperty_last_modified'),
        ('bacnet', '0002_auto_20210930_0917'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='BACnetObject',
            new_name='BACnetVariable',
        ),
        migrations.RenameModel(
            old_name='BACnetObjectProperty',
            new_name='BACnetVariableProperty',
        ),
    ]
