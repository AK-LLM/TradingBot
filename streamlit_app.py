from app.config import load_env_file
load_env_file()
from app.ui import main

if __name__ == "__main__":
    main()