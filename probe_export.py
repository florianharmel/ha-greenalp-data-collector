"""Check GreenAlp login and export interactively."""

import getpass
import warnings

from custom_components.greenalp.client import Client, GreenAlpError
from custom_components.greenalp.normalization import parse_export


def main():
    try:
        username = input("Identifiant GreenAlp : ")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Mot de passe GreenAlp : ")
        readings = parse_export(Client(username, password).export())
    except (GreenAlpError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("Échec de la connexion ou de la validation du CSV.")
        return 1
    count = sum(len(days) for days in readings.values())
    print(f"CSV valide reçu. Nombre de relevés journaliers : {count}.")
    return int(count == 0)


if __name__ == "__main__":
    raise SystemExit(main())
