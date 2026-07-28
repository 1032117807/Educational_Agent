from app.bootstrap import bootstrap


if __name__ == "__main__":
    service, config = bootstrap()
    service.seed_demo()
    print(f"演示数据已就绪：{config.data_dir}")
