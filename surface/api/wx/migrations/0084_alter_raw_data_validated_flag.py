from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wx', '0083_alter_raw_data'),
    ]

    operations = [
        migrations.RunSQL(
            # Apply migration
            sql='''
                -- Clean up existing data so the constraint doesn't fail
                UPDATE public.raw_data 
                SET validated_flag = 1 
                WHERE validated_flag NOT IN (1, 4, 5) OR validated_flag IS NULL;

                -- Alter default and add constraint
                ALTER TABLE public.raw_data
                ALTER COLUMN validated_flag SET DEFAULT 1,
                ADD CONSTRAINT chk_validated_flag CHECK (validated_flag IN (1, 4, 5));
            ''',
            # Revert migration (Rollback logic)
            reverse_sql='''
                ALTER TABLE public.raw_data
                DROP CONSTRAINT IF EXISTS chk_validated_flag,
                ALTER COLUMN validated_flag DROP DEFAULT;
            ''',
        ),
    ]