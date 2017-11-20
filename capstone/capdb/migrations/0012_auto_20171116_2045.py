# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-11-16 20:45
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('capdb', '0011_auto_20171018_1513'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='trackingtoollog',
            options={'ordering': ['created_at']},
        ),
        migrations.AlterField(
            model_name='trackingtoollog',
            name='created_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_tool_logs', to='capdb.TrackingToolUser'),
        ),
        migrations.AlterField(
            model_name='trackingtoollog',
            name='pstep',
            field=models.ForeignKey(blank=True, help_text='A significant event in production', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tracking_tool_logs', to='capdb.ProcessStep'),
        ),
        migrations.AlterField(
            model_name='trackingtoollog',
            name='volume',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_tool_logs', to='capdb.VolumeMetadata'),
        ),
    ]
