from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wx', '0028_crop_soil'),
    ]

    operations = [
        migrations.AddField(
            model_name='crop',
            name='name_spanish',
            field=models.CharField(default=None, help_text='Crop Name in Spanish e.ge. "maíz"', max_length=128, unique=True, verbose_name='Spanish Name'),
            preserve_default=False,
        ),
    ]
