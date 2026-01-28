#  Requirements

Use python to connect to the SolarEdge API and retrieve data and load it into a relational database. Support MariaDB, PostgreSQL, and SQLite databases to store all details about a SolarEdge installation provided by the API and scraping the website. The objective is to harvest as many details as possible about the installation.

This project will provide an efficient way to collect and store data from SolarEdge in a relational database for further analysis and reporting. Running the script on a scheduled basis will regularly update the database with the latest data from SolarEdge, and will capture additional data structures as they become available. The script will also log errors and issues encountered during data retrieval and storage, store timestamps of data retrieval, and handle API rate limiting and retries as needed.

The project will create database tables to store the data retrieved from the SolarEdge API, as well as database views to simplify querying the data. Sister projects may be created to provide reporting and visualization capabilities based on the stored data.

The python script will be designed to be run on a scheduled basis, such as via a cron job, to ensure that the database is regularly updated with the latest data from SolarEdge abiding by their API usage policies. 

Code will execute using `uv`.

## Existing Documentation and Projects

Learn from existing projects and documentation. Use these resources to understand the SolarEdge API and best practices for data retrieval and storage. Borrow ideas and approaches from these resources to inform your own implementation and only use modern, well-maintained libraries, and current best practices and language features.

- SolarEdge Monitoring API Documentation:
https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf

https://github.com/ndejong/solaredge-interface

https://github.com/elliott-davis/solaredge-go

https://github.com/ProudElm/solaredgeoptimizers

## Usage

Run the script. On first run, it will create the database schema and populate it with data from the SolarEdge API. On subsequent runs, it will update the existing data in the database such that the database always reflects the latest data from SolarEdge, and will catch up on any new data structures that have been added since the last run.

```bash