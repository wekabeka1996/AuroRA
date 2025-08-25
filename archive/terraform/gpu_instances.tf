# Terraform конфігурація для AWS/GCP
# terraform/gpu_instances.tf

# Приклад для AWS
resource "aws_instance" "teacher_gpu" {
  ami           = "ami-0c55b159cbfafe1f0" # Deep Learning AMI (Ubuntu 18.04)
  instance_type = "p4d.24xlarge" # A100

  tags = {
    Name = "aurora-teacher"
  }
}

resource "aws_instance" "student_gpu" {
  ami           = "ami-0c55b159cbfafe1f0" # Deep Learning AMI (Ubuntu 18.04)
  instance_type = "p3.8xlarge" # V100

  tags = {
    Name = "aurora-student"
  }
}

# Примітка: Цей код є прикладом і потребує повної конфігурації 
# мережі (VPC, subnets), ключів доступу та інших параметрів для запуску.