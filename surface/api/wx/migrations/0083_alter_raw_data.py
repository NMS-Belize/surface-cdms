from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wx', '0082_alter_station_elevation'),
    ]

    operations = [
        migrations.RunSQL(
            sql='''
                ALTER TABLE public.raw_data
                ADD CONSTRAINT raw_data_validated_flag_fkey
                FOREIGN KEY (validated_flag)
                REFERENCES public.wx_qualityflag(id);
            ''',
            reverse_sql='''
                ALTER TABLE public.raw_data
                DROP CONSTRAINT raw_data_validated_flag_fkey;
            ''',
        ),
    ]