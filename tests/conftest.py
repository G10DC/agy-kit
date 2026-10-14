"""Configurazione pytest: i test del kit NON sono test pytest.

test_bridge.py e test_compendio_verify.py sono script autonomi (main() con check()/ko() che
stampano l'esito, senza assert): pytest li raccoglierebbe lo stesso e darebbe verdi falsi
(funzioni che non sollevano mai) o errori di setup. Vanno lanciati con tests/run-tests.sh,
che esegue tutta la suite (compreso test_install.sh) con il Python trovato dal kit.
"""
collect_ignore = ["test_bridge.py", "test_compendio_verify.py"]
