from django.db import migrations

from tally.adapters import rls


class Migration(migrations.Migration):
    dependencies = [
        ("adapters", "0012_multi_currency"),
    ]

    operations = [
        migrations.RunSQL(rls.enable_sql(), reverse_sql=rls.disable_sql()),
    ]
